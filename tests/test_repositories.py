from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from video_social_bot.config import Settings
from video_social_bot.db import create_engine, create_schema, create_session_factory
from video_social_bot.enums import JobStatus, UploadSource
from video_social_bot.repositories import (
    cancel_tiktok_upload,
    cancel_youtube_publish,
    create_video_job,
    due_tiktok_upload_jobs,
    due_youtube_publish_jobs,
    list_jobs,
    retry_youtube_publish,
    schedule_tiktok_upload,
    schedule_youtube_publish,
)


@pytest.mark.anyio
async def test_youtube_publish_schedule_cancel_and_retry() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
    engine = create_engine(settings)
    await create_schema(engine)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        job = await create_video_job(
            session,
            settings,
            Path("input.mp4"),
            UploadSource.DASHBOARD,
        )
        job.status = JobStatus.READY
        job.processed_file_path = "processed.mp4"
        await schedule_youtube_publish(
            session,
            job,
            datetime.now(UTC) - timedelta(minutes=1),
            "private",
        )
        await session.commit()

        due_jobs = await due_youtube_publish_jobs(session)
        assert [due_job.id for due_job in due_jobs] == [job.id]

        await cancel_youtube_publish(session, job)
        assert job.youtube_publish_status is None
        assert job.youtube_publish_scheduled_at is None

        job.youtube_publish_status = "failed"
        job.youtube_publish_error = "temporary"
        await retry_youtube_publish(session, job)
        assert job.youtube_publish_status == "scheduled"
        assert job.youtube_publish_error is None
    await engine.dispose()


@pytest.mark.anyio
async def test_tiktok_upload_schedule_and_cancel() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
    engine = create_engine(settings)
    await create_schema(engine)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        job = await create_video_job(
            session,
            settings,
            Path("input.mp4"),
            UploadSource.DASHBOARD,
        )
        job.status = JobStatus.READY
        job.processed_file_path = "processed.mp4"
        await schedule_tiktok_upload(session, job, datetime.now(UTC) - timedelta(minutes=1))
        await session.commit()

        due_jobs = await due_tiktok_upload_jobs(session)
        assert [due_job.id for due_job in due_jobs] == [job.id]

        await cancel_tiktok_upload(session, job)
        assert job.tiktok_publish_status is None
        assert job.tiktok_published_at is None
    await engine.dispose()


@pytest.mark.anyio
async def test_list_jobs_filters_by_status_client_and_source() -> None:
    settings = Settings(database_url="sqlite+aiosqlite:///:memory:")
    engine = create_engine(settings)
    await create_schema(engine)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        client_job = await create_video_job(
            session,
            settings,
            Path("client.mp4"),
            UploadSource.CLIENT_PORTAL,
            client_id=123,
        )
        client_job.status = JobStatus.READY
        dashboard_job = await create_video_job(
            session,
            settings,
            Path("dashboard.mp4"),
            UploadSource.DASHBOARD,
        )
        dashboard_job.status = JobStatus.FAILED
        await session.commit()

        ready_jobs = await list_jobs(session, status=JobStatus.READY)
        client_jobs = await list_jobs(session, client_id=123)
        portal_jobs = await list_jobs(session, source=UploadSource.CLIENT_PORTAL)

        assert [job.id for job in ready_jobs] == [client_job.id]
        assert [job.id for job in client_jobs] == [client_job.id]
        assert [job.id for job in portal_jobs] == [client_job.id]
    await engine.dispose()
