from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from video_social_bot.config import Settings
from video_social_bot.enums import CaptionLanguage, JobStatus, UploadSource
from video_social_bot.models import Client, VideoJob


async def get_or_create_telegram_client(
    session: AsyncSession,
    telegram_user_id: int,
    name: str,
) -> Client:
    result = await session.execute(
        select(Client).where(Client.telegram_user_id == telegram_user_id),
    )
    client = result.scalar_one_or_none()
    if client is not None:
        if client.name != name:
            client.name = name
        return client

    client = Client(name=name, telegram_user_id=telegram_user_id)
    session.add(client)
    await session.flush()
    return client


async def create_video_job(
    session: AsyncSession,
    settings: Settings,
    original_file_path: Path,
    source: UploadSource,
    client_id: int | None = None,
    telegram_chat_id: int | None = None,
    telegram_message_id: int | None = None,
) -> VideoJob:
    expires_at = datetime.now(UTC) + timedelta(hours=settings.file_ttl_hours)
    job = VideoJob(
        client_id=client_id,
        telegram_chat_id=telegram_chat_id,
        telegram_message_id=telegram_message_id,
        source=source,
        status=JobStatus.WAITING_LANGUAGE,
        original_file_path=str(original_file_path),
        expires_at=expires_at,
    )
    session.add(job)
    await session.flush()
    return job


async def get_job(session: AsyncSession, job_id: int) -> VideoJob | None:
    result = await session.execute(select(VideoJob).where(VideoJob.id == job_id))
    return result.scalar_one_or_none()


async def set_job_language(
    session: AsyncSession,
    job_id: int,
    language: CaptionLanguage,
) -> VideoJob | None:
    job = await get_job(session, job_id)
    if job is None:
        return None
    job.language = language
    job.status = JobStatus.QUEUED
    job.queued_at = datetime.now(UTC)
    job.error = None
    return job


async def list_jobs(
    session: AsyncSession,
    status: JobStatus | None = None,
    client_id: int | None = None,
) -> list[VideoJob]:
    query: Select[tuple[VideoJob]] = select(VideoJob).order_by(VideoJob.created_at.desc())
    if status is not None:
        query = query.where(VideoJob.status == status)
    if client_id is not None:
        query = query.where(VideoJob.client_id == client_id)
    result = await session.execute(query)
    return list(result.scalars())


async def list_clients(session: AsyncSession) -> list[Client]:
    result = await session.execute(select(Client).order_by(Client.created_at.desc()))
    return list(result.scalars())


async def mark_processing(session: AsyncSession, job: VideoJob) -> None:
    job.status = JobStatus.PROCESSING
    job.started_at = datetime.now(UTC)
    job.error = None


async def mark_ready(
    session: AsyncSession,
    job: VideoJob,
    processed_file_path: Path,
    subtitle_file_path: Path | None,
    transcript: str,
    caption: str,
) -> None:
    job.status = JobStatus.READY
    job.processed_file_path = str(processed_file_path)
    job.subtitle_file_path = str(subtitle_file_path) if subtitle_file_path is not None else None
    job.transcript = transcript
    job.caption = caption
    job.finished_at = datetime.now(UTC)
    job.error = None


async def mark_failed(session: AsyncSession, job: VideoJob, error: str) -> None:
    job.status = JobStatus.FAILED
    job.error = error
    job.finished_at = datetime.now(UTC)


async def expired_jobs(session: AsyncSession) -> list[VideoJob]:
    result = await session.execute(
        select(VideoJob).where(VideoJob.expires_at < datetime.now(UTC)),
    )
    return list(result.scalars())
