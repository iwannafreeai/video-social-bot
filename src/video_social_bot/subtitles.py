from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap

from video_social_bot.config import Settings
from video_social_bot.storage import new_storage_path


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start_seconds: float
    end_seconds: float
    text: str


def format_srt_timestamp(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def split_transcript(transcript: str, max_chars: int) -> list[str]:
    normalized = " ".join(transcript.split())
    if not normalized:
        return []
    return wrap(
        normalized,
        width=max_chars,
        break_long_words=False,
        break_on_hyphens=False,
    )


def build_subtitle_cues(
    transcript: str,
    duration_seconds: float,
    max_chars: int,
) -> list[SubtitleCue]:
    chunks = split_transcript(transcript, max_chars)
    if not chunks:
        return []
    safe_duration = max(duration_seconds, float(len(chunks) * 2))
    cue_duration = safe_duration / len(chunks)
    cues: list[SubtitleCue] = []
    for index, text in enumerate(chunks, start=1):
        start_seconds = (index - 1) * cue_duration
        end_seconds = min(index * cue_duration, safe_duration)
        cues.append(
            SubtitleCue(
                index=index,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                text=text,
            ),
        )
    return cues


def render_srt(cues: list[SubtitleCue]) -> str:
    blocks = [
        "\n".join(
            [
                str(cue.index),
                f"{format_srt_timestamp(cue.start_seconds)} --> "
                f"{format_srt_timestamp(cue.end_seconds)}",
                cue.text,
            ],
        )
        for cue in cues
    ]
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def write_srt_file(settings: Settings, transcript: str, duration_seconds: float) -> Path | None:
    if not settings.subtitles_enabled:
        return None
    cues = build_subtitle_cues(
        transcript=transcript,
        duration_seconds=duration_seconds,
        max_chars=settings.subtitle_max_chars,
    )
    if not cues:
        return None
    output_path = new_storage_path(settings, "subtitles", ".srt")
    output_path.write_text(render_srt(cues), encoding="utf-8")
    return output_path


def escape_subtitles_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:")


def subtitles_filter(settings: Settings, subtitle_path: Path | None) -> str | None:
    if subtitle_path is None or not settings.burn_subtitles:
        return None
    escaped_path = escape_subtitles_path(subtitle_path)
    force_style = (
        "FontName=Arial,"
        f"FontSize={settings.subtitle_font_size},"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Shadow=0,"
        "Alignment=2,"
        "MarginV=120"
    )
    return f"subtitles='{escaped_path}':force_style='{force_style}'"
