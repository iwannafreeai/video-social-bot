from pathlib import Path

from video_social_bot.config import Settings
from video_social_bot.storage import ensure_storage_dirs, new_storage_path


def test_new_storage_path_creates_folder(tmp_path: Path) -> None:
    settings = Settings(storage_dir=tmp_path)

    path = new_storage_path(settings, "incoming", ".mp4")

    assert path.parent.exists()
    assert path.suffix == ".mp4"


def test_ensure_storage_dirs(tmp_path: Path) -> None:
    settings = Settings(storage_dir=tmp_path)

    ensure_storage_dirs(settings)

    assert (tmp_path / "incoming").is_dir()
    assert (tmp_path / "processed").is_dir()
    assert (tmp_path / "audio").is_dir()
    assert (tmp_path / "frames").is_dir()
