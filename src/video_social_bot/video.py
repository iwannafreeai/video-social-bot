import asyncio
import json
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path

from video_social_bot.config import Settings
from video_social_bot.models import Client
from video_social_bot.storage import new_storage_path
from video_social_bot.subtitles import subtitles_filter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    width: int
    height: int


async def run_command(args: list[str]) -> str:
    logger.debug("Running command: %s", " ".join(shlex.quote(arg) for arg in args))
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0:
        logger.error("Command failed with exit code %s: %s", process.returncode, stderr_text)
        msg = f"Command failed: {' '.join(args)}\n{stderr_text}"
        raise RuntimeError(msg)
    if stderr_text:
        logger.debug("Command stderr: %s", stderr_text)
    return stdout.decode("utf-8", errors="replace")


async def probe_video(path: Path) -> VideoProbe:
    logger.info("Probing video: %s", path)
    output = await run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-of",
            "json",
            str(path),
        ],
    )
    data = json.loads(output)
    streams = data.get("streams", [])
    if not streams:
        msg = "No video stream found"
        raise ValueError(msg)
    stream = streams[0]
    probe = VideoProbe(
        duration_seconds=float(stream.get("duration") or 0),
        width=int(stream["width"]),
        height=int(stream["height"]),
    )
    logger.info(
        "Video probe complete: path=%s width=%s height=%s duration=%.2f",
        path,
        probe.width,
        probe.height,
        probe.duration_seconds,
    )
    return probe


async def extract_audio(settings: Settings, input_path: Path) -> Path:
    output_path = new_storage_path(settings, "audio", ".mp3")
    logger.info("Extracting audio: input=%s output=%s", input_path, output_path)
    await run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-b:a",
            "64k",
            str(output_path),
        ],
    )
    logger.info("Audio extracted: %s", output_path)
    return output_path


async def extract_preview_frames(
    settings: Settings,
    input_path: Path,
    count: int = 3,
) -> list[Path]:
    await probe_video(input_path)
    output_dir = settings.storage_dir / "frames" / input_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    output_pattern = output_dir / "frame_%02d.jpg"
    await run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            f"fps=1/{max(count, 1)},scale=360:-1",
            "-frames:v",
            str(count),
            str(output_pattern),
        ],
    )
    frames = sorted(output_dir.glob("frame_*.jpg"))
    logger.info("Extracted %s preview frames for %s", len(frames), input_path)
    return frames


@dataclass(frozen=True)
class WatermarkSettings:
    text: str
    font_size: int
    opacity: float
    position: str


def resolve_watermark_settings(
    settings: Settings,
    client: Client | None = None,
) -> WatermarkSettings | None:
    text = client.watermark_text if client and client.watermark_text else settings.watermark_text
    if not text:
        return None
    font_size = client.watermark_font_size if client and client.watermark_font_size else None
    opacity = client.watermark_opacity if client and client.watermark_opacity is not None else None
    position = client.watermark_position if client and client.watermark_position else None
    return WatermarkSettings(
        text=text,
        font_size=font_size or settings.watermark_font_size,
        opacity=(opacity / 100) if opacity is not None else settings.watermark_opacity,
        position=position or settings.watermark_position,
    )


def watermark_filter(settings: Settings, client: Client | None = None) -> str | None:
    watermark_settings = resolve_watermark_settings(settings, client)
    if watermark_settings is None:
        return None
    escaped_text = (
        watermark_settings.text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    )
    alpha = f"{watermark_settings.opacity:.2f}"
    positions = {
        "top-left": ("40", "40"),
        "top-right": ("w-tw-40", "40"),
        "bottom-left": ("40", "h-th-40"),
        "bottom-right": ("w-tw-40", "h-th-40"),
    }
    x, y = positions[watermark_settings.position]
    return (
        "drawtext="
        f"text='{escaped_text}':"
        "fontcolor=white@"
        f"{alpha}:fontsize={watermark_settings.font_size}:"
        "box=1:boxcolor=black@0.25:boxborderw=12:"
        f"x={x}:y={y}"
    )


async def remaster_video(
    settings: Settings,
    input_path: Path,
    subtitle_path: Path | None = None,
    client: Client | None = None,
) -> Path:
    output_path = new_storage_path(settings, "processed", ".mp4")
    filter_parts = [
        "scale=1080:1920:force_original_aspect_ratio=decrease",
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "eq=contrast=1.03:saturation=1.04:brightness=0.01",
        "setsar=1",
    ]
    watermark = watermark_filter(settings, client)
    if watermark is not None:
        filter_parts.append(watermark)
    subtitle_filter = subtitles_filter(settings, subtitle_path)
    if subtitle_filter is not None:
        filter_parts.append(subtitle_filter)
    filters = ",".join(filter_parts)
    logger.info(
        "Remastering video: input=%s output=%s watermark=%s subtitles=%s",
        input_path,
        output_path,
        bool(watermark),
        bool(subtitle_filter),
    )
    await run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            filters,
            "-c:v",
            "libx264",
            "-preset",
            settings.ffmpeg_preset,
            "-crf",
            str(settings.output_crf),
            "-c:a",
            "aac",
            "-b:a",
            settings.output_audio_bitrate,
            "-movflags",
            "+faststart",
            str(output_path),
        ],
    )
    logger.info("Video remastered: %s", output_path)
    return output_path
