import asyncio
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from video_social_bot.config import Settings, get_settings
from video_social_bot.db import create_engine, create_schema, create_session_factory
from video_social_bot.enums import CaptionLanguage, UploadSource
from video_social_bot.repositories import (
    create_video_job,
    get_or_create_telegram_client,
    set_job_language,
)
from video_social_bot.storage import ensure_storage_dirs, new_storage_path
from video_social_bot.worker import JobWorker

logger = logging.getLogger(__name__)


def language_keyboard(job_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Русский", callback_data=f"lang:{job_id}:ru"),
                InlineKeyboardButton(text="English", callback_data=f"lang:{job_id}:en"),
            ],
        ],
    )


def build_router(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await message.answer(
            "Загрузи вертикальное видео до "
            f"{settings.max_upload_mb} МБ. Я обработаю файл и подготовлю подпись."
        )

    @router.message(F.video | F.document)
    async def receive_video(message: Message, bot: Bot) -> None:
        telegram_file = message.video or message.document
        if telegram_file is None:
            return
        file_size = telegram_file.file_size or 0
        max_bytes = settings.max_upload_mb * 1024 * 1024
        if file_size > max_bytes:
            await message.answer(f"Файл больше лимита {settings.max_upload_mb} МБ.")
            return

        suffix = Path(telegram_file.file_name or "video.mp4").suffix or ".mp4"
        destination = new_storage_path(settings, "incoming", suffix)
        await bot.download(telegram_file, destination=destination)

        user = message.from_user
        if user is None:
            await message.answer("Не удалось определить Telegram-пользователя.")
            return

        display_name = user.full_name or user.username or str(user.id)
        async with session_factory() as session:
            client = await get_or_create_telegram_client(session, user.id, display_name)
            job = await create_video_job(
                session=session,
                settings=settings,
                original_file_path=destination,
                source=UploadSource.TELEGRAM,
                client_id=client.id,
                telegram_chat_id=message.chat.id,
                telegram_message_id=message.message_id,
            )
            await session.commit()

        await message.answer(
            f"Видео принято. Задача #{job.id}. Выбери язык подписи:",
            reply_markup=language_keyboard(job.id),
        )

    @router.callback_query(F.data.startswith("lang:"))
    async def choose_language(callback: CallbackQuery) -> None:
        data = callback.data or ""
        _, raw_job_id, raw_language = data.split(":")
        language = CaptionLanguage(raw_language)
        async with session_factory() as session:
            job = await set_job_language(session, int(raw_job_id), language)
            await session.commit()
        if job is None:
            await callback.answer("Задача не найдена", show_alert=True)
            return
        if isinstance(callback.message, Message):
            await callback.message.answer(f"Задача #{job.id} поставлена в очередь.")
        await callback.answer()

    return router


async def run_bot() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    if not settings.telegram_bot_token:
        msg = "TELEGRAM_BOT_TOKEN is required"
        raise RuntimeError(msg)
    ensure_storage_dirs(settings)
    engine = create_engine(settings)
    await create_schema(engine)
    session_factory = create_session_factory(engine)
    bot = Bot(settings.telegram_bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(settings, session_factory))
    worker = JobWorker(settings, session_factory, bot)
    worker_task = asyncio.create_task(worker.run_forever())
    try:
        await dispatcher.start_polling(bot)
    finally:
        worker.stop()
        worker_task.cancel()
        await engine.dispose()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run_bot())
