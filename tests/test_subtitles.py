from pathlib import Path

from video_social_bot.config import Settings
from video_social_bot.subtitles import (
    build_segment_subtitle_cues,
    build_subtitle_cues,
    format_srt_timestamp,
    render_srt,
    subtitles_filter,
    write_srt_file,
)


def test_format_srt_timestamp() -> None:
    assert format_srt_timestamp(65.432) == "00:01:05,432"


def test_build_subtitle_cues_splits_transcript() -> None:
    cues = build_subtitle_cues(
        "one two three four five six seven eight",
        duration_seconds=8,
        max_chars=12,
    )

    assert len(cues) > 1
    assert cues[0].index == 1
    assert cues[-1].end_seconds == 8


def test_render_srt() -> None:
    cues = build_subtitle_cues("hello world", duration_seconds=2, max_chars=42)

    content = render_srt(cues)

    assert content == "1\n00:00:00,000 --> 00:00:02,000\nhello world\n"


def test_build_segment_subtitle_cues_uses_segment_timing() -> None:
    cues = build_segment_subtitle_cues(
        [(1.0, 3.0, "hello world"), (4.0, 6.0, "next line")],
        max_chars=42,
    )

    assert len(cues) == 2
    assert cues[0].start_seconds == 1.0
    assert cues[0].end_seconds == 3.0
    assert cues[1].start_seconds == 4.0


def test_write_srt_file(tmp_path: Path) -> None:
    settings = Settings(storage_dir=tmp_path)

    path = write_srt_file(settings, "hello world", duration_seconds=2)

    assert path is not None
    assert path.read_text(encoding="utf-8").startswith("1\n00:00:00,000")


def test_write_srt_file_prefers_segments(tmp_path: Path) -> None:
    settings = Settings(storage_dir=tmp_path)

    path = write_srt_file(
        settings,
        "fallback text",
        duration_seconds=10,
        segments=[(2.0, 4.0, "segment text")],
    )

    assert path is not None
    assert "00:00:02,000 --> 00:00:04,000" in path.read_text(encoding="utf-8")


def test_write_srt_file_disabled(tmp_path: Path) -> None:
    settings = Settings(storage_dir=tmp_path, subtitles_enabled=False)

    path = write_srt_file(settings, "hello world", duration_seconds=2)

    assert path is None


def test_subtitles_filter() -> None:
    settings = Settings(burn_subtitles=True, subtitle_font_size=50)

    result = subtitles_filter(settings, Path("/tmp/test.srt"))

    assert result is not None
    assert "subtitles=" in result
    assert "FontSize=50" in result


def test_subtitles_filter_disabled() -> None:
    settings = Settings(burn_subtitles=False)

    result = subtitles_filter(settings, Path("/tmp/test.srt"))

    assert result is None
