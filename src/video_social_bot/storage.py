import os
import shutil
from pathlib import Path
from uuid import uuid4

import aiofiles
from starlette.datastructures import UploadFile

from video_social_bot.config import Settings


def ensure_storage_dirs(settings: Settings) -> None:
    for name in ("incoming", "processed", "audio", "frames"):
        (settings.storage_dir / name).mkdir(parents=True, exist_ok=True)


def new_storage_path(settings: Settings, folder: str, suffix: str) -> Path:
    ensure_storage_dirs(settings)
    safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
    return settings.storage_dir / folder / f"{uuid4().hex}{safe_suffix}"


async def save_upload_file(upload_file: UploadFile, destination: Path, max_bytes: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    async with aiofiles.open(destination, "wb") as handle:
        while chunk := await upload_file.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                await handle.close()
                destination.unlink(missing_ok=True)
                msg = "Uploaded file is too large"
                raise ValueError(msg)
            await handle.write(chunk)
    return written


def delete_path(path: str | None) -> None:
    if not path:
        return
    candidate = Path(path)
    if candidate.is_file():
        candidate.unlink(missing_ok=True)
    elif candidate.is_dir():
        shutil.rmtree(candidate, ignore_errors=True)


def file_size_mb(path: Path) -> float:
    return os.path.getsize(path) / 1024 / 1024
