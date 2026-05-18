from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import Select, or_, select
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
    source: UploadSource | None = None,
) -> list[VideoJob]:
    query: Select[tuple[VideoJob]] = select(VideoJob).order_by(VideoJob.created_at.desc())
    if status is not None:
        query = query.where(VideoJob.status == status)
    if client_id is not None:
        query = query.where(VideoJob.client_id == client_id)
    if source is not None:
        query = query.where(VideoJob.source == source)
    result = await session.execute(query)
    return list(result.scalars())


async def list_clients(session: AsyncSession) -> list[Client]:
    result = await session.execute(select(Client).order_by(Client.created_at.desc()))
    return list(result.scalars())


async def get_client(session: AsyncSession, client_id: int) -> Client | None:
    result = await session.execute(select(Client).where(Client.id == client_id))
    return result.scalar_one_or_none()


async def update_client_branding(
    session: AsyncSession,
    client_id: int,
    watermark_text: str,
    watermark_position: str | None,
    watermark_opacity: int | None,
    watermark_font_size: int | None,
) -> Client | None:
    client = await get_client(session, client_id)
    if client is None:
        return None
    client.watermark_text = watermark_text.strip() or None
    client.watermark_position = watermark_position
    client.watermark_opacity = watermark_opacity
    client.watermark_font_size = watermark_font_size
    return client


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


async def mark_youtube_published(session: AsyncSession, job: VideoJob, video_id: str) -> None:
    job.youtube_video_id = video_id
    job.youtube_published_at = datetime.now(UTC)
    job.youtube_publish_status = "published"
    job.youtube_publish_error = None


async def schedule_youtube_publish(
    session: AsyncSession,
    job: VideoJob,
    scheduled_at: datetime,
    privacy_status: str,
) -> None:
    job.youtube_publish_status = "scheduled"
    job.youtube_publish_scheduled_at = scheduled_at
    job.youtube_publish_privacy = privacy_status
    job.youtube_publish_attempts = 0
    job.youtube_publish_error = None


async def mark_youtube_publish_attempt(session: AsyncSession, job: VideoJob) -> None:
    job.youtube_publish_attempts = (job.youtube_publish_attempts or 0) + 1
    job.youtube_publish_status = "publishing"
    job.youtube_publish_error = None


async def mark_youtube_publish_retry(
    session: AsyncSession,
    job: VideoJob,
    error: str,
    retry_at: datetime,
) -> None:
    job.youtube_publish_status = "scheduled"
    job.youtube_publish_scheduled_at = retry_at
    job.youtube_publish_error = error


async def mark_youtube_publish_failed(session: AsyncSession, job: VideoJob, error: str) -> None:
    job.youtube_publish_status = "failed"
    job.youtube_publish_error = error


async def cancel_youtube_publish(session: AsyncSession, job: VideoJob) -> None:
    job.youtube_publish_status = None
    job.youtube_publish_scheduled_at = None
    job.youtube_publish_privacy = None
    job.youtube_publish_error = None


async def retry_youtube_publish(session: AsyncSession, job: VideoJob) -> None:
    job.youtube_publish_status = "scheduled"
    job.youtube_publish_scheduled_at = datetime.now(UTC)
    job.youtube_publish_attempts = 0
    job.youtube_publish_error = None


async def due_youtube_publish_jobs(session: AsyncSession) -> list[VideoJob]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(VideoJob)
        .where(VideoJob.status == JobStatus.READY)
        .where(VideoJob.processed_file_path.is_not(None))
        .where(VideoJob.youtube_video_id.is_(None))
        .where(VideoJob.youtube_publish_status == "scheduled")
        .where(
            or_(
                VideoJob.youtube_publish_scheduled_at.is_(None),
                VideoJob.youtube_publish_scheduled_at <= now,
            ),
        )
        .order_by(VideoJob.youtube_publish_scheduled_at.asc()),
    )
    return list(result.scalars())


async def mark_tiktok_uploaded(session: AsyncSession, job: VideoJob, publish_id: str) -> None:
    job.tiktok_publish_id = publish_id
    job.tiktok_publish_status = "uploaded"
    job.tiktok_published_at = datetime.now(UTC)
    job.tiktok_publish_error = None


async def schedule_tiktok_upload(
    session: AsyncSession,
    job: VideoJob,
    scheduled_at: datetime,
) -> None:
    job.tiktok_publish_status = "scheduled"
    job.tiktok_published_at = scheduled_at
    job.tiktok_publish_error = None


async def mark_tiktok_attempt(session: AsyncSession, job: VideoJob) -> None:
    job.tiktok_publish_status = "uploading"
    job.tiktok_publish_error = None


async def mark_tiktok_failed(session: AsyncSession, job: VideoJob, error: str) -> None:
    job.tiktok_publish_status = "failed"
    job.tiktok_publish_error = error


async def cancel_tiktok_upload(session: AsyncSession, job: VideoJob) -> None:
    job.tiktok_publish_status = None
    job.tiktok_published_at = None
    job.tiktok_publish_error = None


async def due_tiktok_upload_jobs(session: AsyncSession) -> list[VideoJob]:
    now = datetime.now(UTC)
    result = await session.execute(
        select(VideoJob)
        .where(VideoJob.status == JobStatus.READY)
        .where(VideoJob.processed_file_path.is_not(None))
        .where(VideoJob.tiktok_publish_id.is_(None))
        .where(VideoJob.tiktok_publish_status == "scheduled")
        .where(
            or_(
                VideoJob.tiktok_published_at.is_(None),
                VideoJob.tiktok_published_at <= now,
            ),
        )
        .order_by(VideoJob.tiktok_published_at.asc()),
    )
    return list(result.scalars())


async def expired_jobs(session: AsyncSession) -> list[VideoJob]:
    result = await session.execute(
        select(VideoJob).where(VideoJob.expires_at < datetime.now(UTC)),
    )
    return list(result.scalars())
