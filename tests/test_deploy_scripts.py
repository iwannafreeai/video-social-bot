from pathlib import Path


def test_backup_restore_scripts_exist_and_are_executable() -> None:
    root = Path(__file__).resolve().parents[1]
    backup = root / "scripts" / "backup.sh"
    restore = root / "scripts" / "restore.sh"

    assert backup.exists()
    assert restore.exists()
    assert backup.stat().st_mode & 0o111
    assert restore.stat().st_mode & 0o111


def test_backup_script_uses_named_volumes() -> None:
    root = Path(__file__).resolve().parents[1]
    content = (root / "scripts" / "backup.sh").read_text(encoding="utf-8")

    assert "DATA_VOLUME" in content
    assert "STORAGE_VOLUME" in content
    assert "app-data.tgz" in content
    assert "app-storage.tgz" in content
