import asyncio

from video_social_bot.config import get_settings
from video_social_bot.db import create_engine, create_schema
from video_social_bot.storage import ensure_storage_dirs


async def init_db() -> None:
    settings = get_settings()
    ensure_storage_dirs(settings)
    engine = create_engine(settings)
    await create_schema(engine)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init_db())
