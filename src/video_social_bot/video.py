import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from video_social_bot.config import Settings
from video_social_bot.storage import new_storage_path


@dataclass(frozen=True)
class VideoProbe:
    duration_seconds: float
    width: int
    height: int


async def run_command(args: list[str]) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        error_text = stderr.decode("utf-8", errors="replace").strip()
        msg = f"Command failed: {' '.join(args)}\n{error_text}"
        raise RuntimeError(msg)
    return stdout.decode("utf-8", errors="replace")


async def probe_video(path: Path) -> VideoProbe:
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
    return VideoProbe(
        duration_seconds=float(stream.get("duration") or 0),
        width=int(stream["width"]),
        height=int(stream["height"]),
    )


async def extract_audio(settings: Settings, input_path: Path) -> Path:
    output_path = new_storage_path(settings, "audio", ".mp3")
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
    return sorted(output_dir.glob("frame_*.jpg"))


async def remaster_video(settings: Settings, input_path: Path) -> Path:
    output_path = new_storage_path(settings, "processed", ".mp4")
    filters = ",".join(
        [
            "scale=1080:1920:force_original_aspect_ratio=decrease",
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "eq=contrast=1.03:saturation=1.04:brightness=0.01",
            "setsar=1",
        ],
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
    return output_path
