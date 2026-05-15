import asyncio
import contextlib
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from video_social_bot.ai import CaptionClient, TranscriptionClient
from video_social_bot.config import Settings
from video_social_bot.enums import JobStatus
from video_social_bot.repositories import (
    expired_jobs,
    get_job,
    list_jobs,
    mark_failed,
    mark_processing,
    mark_ready,
)
from video_social_bot.storage import delete_path
from video_social_bot.subtitles import write_srt_file
from video_social_bot.video import extract_audio, probe_video, remaster_video

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

    async def process_job(self, job_id: int) -> None:
        logger.info("Processing job #%s", job_id)
        async with self._session_factory() as session:
            job = await get_job(session, job_id)
            if job is None or job.language is None:
                logger.warning("Skipping job #%s: missing job or language", job_id)
                return
            input_path = Path(job.original_file_path)

        try:
            audio_path = await extract_audio(self._settings, input_path)
            transcript = await TranscriptionClient(self._settings).transcribe(audio_path)
            caption = await CaptionClient(self._settings).generate_caption(transcript, job.language)
            probe = await probe_video(input_path)
            subtitle_path = write_srt_file(
                self._settings,
                transcript,
                duration_seconds=probe.duration_seconds,
            )
            processed_path = await remaster_video(self._settings, input_path, subtitle_path)
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
            await mark_ready(session, ready_job, processed_path, subtitle_path, transcript, caption)
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
