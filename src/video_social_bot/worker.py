import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from video_social_bot.ai import CaptionClient, TranscriptionClient
from video_social_bot.config import Settings
from video_social_bot.enums import JobStatus
from video_social_bot.repositories import (
    due_tiktok_upload_jobs,
    due_youtube_publish_jobs,
    expired_jobs,
    get_client,
    get_job,
    list_jobs,
    mark_failed,
    mark_processing,
    mark_ready,
    mark_tiktok_attempt,
    mark_tiktok_failed,
    mark_tiktok_uploaded,
    mark_youtube_publish_attempt,
    mark_youtube_publish_failed,
    mark_youtube_publish_retry,
    mark_youtube_published,
)
from video_social_bot.storage import delete_path
from video_social_bot.subtitles import write_srt_file
from video_social_bot.tiktok import tiktok_connected, upload_tiktok_video_to_inbox
from video_social_bot.video import extract_audio, probe_video, remaster_video
from video_social_bot.youtube import build_youtube_title, upload_youtube_video, youtube_connected

logger = logging.getLogger(__name__)


class JobWorker:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        bot: Bot | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._bot = bot
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        logger.info("Worker started")
        while self._running:
            try:
                await self.process_next()
                await self.process_due_youtube_publishes()
                await self.process_due_tiktok_uploads()
                await self.cleanup_expired()
            except Exception:
                logger.exception("Worker loop failed")
            await asyncio.sleep(5)

    def stop(self) -> None:
        logger.info("Worker stopping")
        self._running = False

    async def process_next(self) -> None:
        async with self._session_factory() as session:
            jobs = await list_jobs(session, status=JobStatus.QUEUED)
            if not jobs:
                return
            job = jobs[-1]
            logger.info("Dequeued job #%s", job.id)
            await mark_processing(session, job)
            await session.commit()
            job_id = job.id

        await self.process_job(job_id)

    async def process_due_youtube_publishes(self) -> None:
        if not youtube_connected(self._settings):
            return
        async with self._session_factory() as session:
            jobs = await due_youtube_publish_jobs(session)
            if not jobs:
                return
            job = jobs[0]
            await mark_youtube_publish_attempt(session, job)
            await session.commit()
            job_id = job.id

        await self.publish_youtube_job(job_id)

    async def process_due_tiktok_uploads(self) -> None:
        if not tiktok_connected(self._settings):
            return
        async with self._session_factory() as session:
            jobs = await due_tiktok_upload_jobs(session)
            if not jobs:
                return
            job = jobs[0]
            await mark_tiktok_attempt(session, job)
            await session.commit()
            job_id = job.id

        await self.upload_tiktok_job(job_id)

    async def upload_tiktok_job(self, job_id: int) -> None:
        async with self._session_factory() as session:
            job = await get_job(session, job_id)
            if job is None or not job.processed_file_path:
                return
            video_path = Path(job.processed_file_path)

        try:
            result = await upload_tiktok_video_to_inbox(self._settings, video_path)
        except Exception as exc:
            logger.exception("Scheduled TikTok upload failed: job_id=%s", job_id)
            async with self._session_factory() as session:
                failed_job = await get_job(session, job_id)
                if failed_job is not None:
                    await mark_tiktok_failed(session, failed_job, str(exc))
                    await session.commit()
            return

        async with self._session_factory() as session:
            uploaded_job = await get_job(session, job_id)
            if uploaded_job is not None:
                await mark_tiktok_uploaded(session, uploaded_job, result.publish_id)
                await session.commit()

    async def publish_youtube_job(self, job_id: int) -> None:
        async with self._session_factory() as session:
            job = await get_job(session, job_id)
            if job is None or not job.processed_file_path:
                return
            video_path = Path(job.processed_file_path)
            privacy_status = (
                job.youtube_publish_privacy or self._settings.youtube_default_privacy_status
            )
            attempts = job.youtube_publish_attempts or 0
            caption = job.caption

        try:
            video_id = await upload_youtube_video(
                settings=self._settings,
                video_path=video_path,
                title=build_youtube_title(job_id, caption),
                description=caption or "",
                privacy_status=privacy_status,
            )
        except Exception as exc:
            logger.exception("Scheduled YouTube publish failed: job_id=%s", job_id)
            async with self._session_factory() as session:
                failed_job = await get_job(session, job_id)
                if failed_job is None:
                    return
                if attempts < self._settings.youtube_publish_retry_limit:
                    await mark_youtube_publish_retry(
                        session,
                        failed_job,
                        str(exc),
                        datetime.now(UTC)
                        + timedelta(seconds=self._settings.youtube_publish_retry_delay_seconds),
                    )
                else:
                    await mark_youtube_publish_failed(session, failed_job, str(exc))
                await session.commit()
            return

        async with self._session_factory() as session:
            published_job = await get_job(session, job_id)
            if published_job is not None:
                await mark_youtube_published(session, published_job, video_id)
                await session.commit()

    async def process_job(self, job_id: int) -> None:
        logger.info("Processing job #%s", job_id)
        async with self._session_factory() as session:
            job = await get_job(session, job_id)
            if job is None or job.language is None:
                logger.warning("Skipping job #%s: missing job or language", job_id)
                return
            input_path = Path(job.original_file_path)
            client = await get_client(session, job.client_id) if job.client_id is not None else None

        try:
            audio_path = await extract_audio(self._settings, input_path)
            transcription = await TranscriptionClient(self._settings).transcribe(audio_path)
            caption = await CaptionClient(self._settings).generate_caption(
                transcription.text,
                job.language,
            )
            probe = await probe_video(input_path)
            subtitle_path = write_srt_file(
                self._settings,
                transcription.text,
                duration_seconds=probe.duration_seconds,
                segments=[
                    (segment.start_seconds, segment.end_seconds, segment.text)
                    for segment in transcription.segments
                ],
            )
            processed_path = await remaster_video(self._settings, input_path, subtitle_path, client)
        except Exception as exc:
            logger.exception("Job #%s failed", job_id)
            async with self._session_factory() as session:
                failed_job = await get_job(session, job_id)
                if failed_job is not None:
                    await mark_failed(session, failed_job, str(exc))
                    await session.commit()
                    await self._notify_failure(failed_job.telegram_chat_id, failed_job.id, str(exc))
            return

        async with self._session_factory() as session:
            ready_job = await get_job(session, job_id)
            if ready_job is None:
                return
            await mark_ready(
                session,
                ready_job,
                processed_path,
                subtitle_path,
                transcription.text,
                caption,
            )
            await session.commit()
            logger.info("Job #%s ready: %s", job_id, processed_path)
            await self._notify_ready(
                ready_job.telegram_chat_id,
                ready_job.id,
                processed_path,
                subtitle_path,
                caption,
            )

        with contextlib.suppress(NameError):
            delete_path(str(audio_path))

    async def cleanup_expired(self) -> None:
        async with self._session_factory() as session:
            jobs = await expired_jobs(session)
            for job in jobs:
                logger.info("Deleting expired job #%s", job.id)
                delete_path(job.original_file_path)
                delete_path(job.processed_file_path)
                delete_path(job.subtitle_file_path)
                await session.delete(job)
            await session.commit()

    async def _notify_ready(
        self,
        telegram_chat_id: int | None,
        job_id: int,
        processed_path: Path,
        subtitle_path: Path | None,
        caption: str,
    ) -> None:
        if self._bot is None or telegram_chat_id is None:
            return
        await self._bot.send_message(
            telegram_chat_id,
            f"Готово. Задача #{job_id}\n\nПодпись:\n{caption}",
        )
        await self._bot.send_document(telegram_chat_id, FSInputFile(processed_path))
        if subtitle_path is not None:
            await self._bot.send_document(telegram_chat_id, FSInputFile(subtitle_path))

    async def _notify_failure(
        self,
        telegram_chat_id: int | None,
        job_id: int,
        error: str,
    ) -> None:
        if self._bot is None or telegram_chat_id is None:
            return
        await self._bot.send_message(telegram_chat_id, f"Ошибка в задаче #{job_id}: {error}")
