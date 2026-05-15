import asyncio
import json
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path

from video_social_bot.config import Settings
from video_social_bot.storage import new_storage_path

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


def watermark_filter(settings: Settings) -> str | None:
    if not settings.watermark_text:
        return None
    escaped_text = settings.watermark_text.replace("\\", "\\\\").replace(":", "\\:")
    alpha = f"{settings.watermark_opacity:.2f}"
    positions = {
        "top-left": ("40", "40"),
        "top-right": ("w-tw-40", "40"),
        "bottom-left": ("40", "h-th-40"),
        "bottom-right": ("w-tw-40", "h-th-40"),
    }
    x, y = positions[settings.watermark_position]
    return (
        "drawtext="
        f"text='{escaped_text}':"
        "fontcolor=white@"
        f"{alpha}:fontsize={settings.watermark_font_size}:"
        "box=1:boxcolor=black@0.25:boxborderw=12:"
        f"x={x}:y={y}"
    )


async def remaster_video(settings: Settings, input_path: Path) -> Path:
    output_path = new_storage_path(settings, "processed", ".mp4")
    filter_parts = [
        "scale=1080:1920:force_original_aspect_ratio=decrease",
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
        "eq=contrast=1.03:saturation=1.04:brightness=0.01",
        "setsar=1",
    ]
    watermark = watermark_filter(settings)
    if watermark is not None:
        filter_parts.append(watermark)
    filters = ",".join(filter_parts)
    logger.info(
        "Remastering video: input=%s output=%s watermark=%s",
        input_path,
        output_path,
        bool(watermark),
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
