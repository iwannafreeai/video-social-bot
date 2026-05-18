from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from video_social_bot.config import Settings

SQLITE_MIGRATIONS = {
    "video_jobs": {
        "subtitle_file_path": "ALTER TABLE video_jobs ADD COLUMN subtitle_file_path TEXT",
        "youtube_video_id": "ALTER TABLE video_jobs ADD COLUMN youtube_video_id VARCHAR(64)",
        "youtube_published_at": "ALTER TABLE video_jobs ADD COLUMN youtube_published_at DATETIME",
        "youtube_publish_status": (
            "ALTER TABLE video_jobs ADD COLUMN youtube_publish_status VARCHAR(32)"
        ),
        "youtube_publish_privacy": (
            "ALTER TABLE video_jobs ADD COLUMN youtube_publish_privacy VARCHAR(16)"
        ),
        "youtube_publish_scheduled_at": (
            "ALTER TABLE video_jobs ADD COLUMN youtube_publish_scheduled_at DATETIME"
        ),
        "youtube_publish_attempts": (
            "ALTER TABLE video_jobs ADD COLUMN youtube_publish_attempts INTEGER DEFAULT 0"
        ),
        "youtube_publish_error": "ALTER TABLE video_jobs ADD COLUMN youtube_publish_error TEXT",
        "tiktok_publish_id": "ALTER TABLE video_jobs ADD COLUMN tiktok_publish_id VARCHAR(128)",
        "tiktok_publish_status": (
            "ALTER TABLE video_jobs ADD COLUMN tiktok_publish_status VARCHAR(64)"
        ),
        "tiktok_published_at": "ALTER TABLE video_jobs ADD COLUMN tiktok_published_at DATETIME",
        "tiktok_publish_error": "ALTER TABLE video_jobs ADD COLUMN tiktok_publish_error TEXT",
    },
    "clients": {
        "watermark_text": "ALTER TABLE clients ADD COLUMN watermark_text VARCHAR(120)",
        "watermark_position": "ALTER TABLE clients ADD COLUMN watermark_position VARCHAR(32)",
        "watermark_opacity": "ALTER TABLE clients ADD COLUMN watermark_opacity INTEGER",
        "watermark_font_size": "ALTER TABLE clients ADD COLUMN watermark_font_size INTEGER",
    },
}


class Base(DeclarativeBase):
    pass


def ensure_sqlite_parent(database_url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return
    path = database_url.removeprefix(prefix)
    if path == ":memory:":
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def create_engine(settings: Settings) -> AsyncEngine:
    ensure_sqlite_parent(settings.database_url)
    return create_async_engine(settings.database_url, echo=False)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def create_schema(engine: AsyncEngine) -> None:
    from video_social_bot import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.url.get_backend_name() == "sqlite":
            for table_name, migrations in SQLITE_MIGRATIONS.items():
                columns = await conn.exec_driver_sql(f"PRAGMA table_info({table_name})")
                existing = {row[1] for row in columns.fetchall()}
                for column_name, statement in migrations.items():
                    if column_name not in existing:
                        await conn.exec_driver_sql(statement)


@asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
