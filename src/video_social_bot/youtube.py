import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from video_social_bot.config import Settings

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


@dataclass(frozen=True)
class YouTubeToken:
    access_token: str
    refresh_token: str
    expires_at: datetime
    token_type: str = "Bearer"


def youtube_configured(settings: Settings) -> bool:
    return bool(settings.youtube_client_id and settings.youtube_client_secret)


def youtube_redirect_uri(settings: Settings) -> str:
    if settings.youtube_redirect_uri:
        return settings.youtube_redirect_uri
    return f"{settings.app_base_url.rstrip('/')}/integrations/youtube/callback"


def build_youtube_auth_url(settings: Settings, state: str) -> str:
    query = {
        "client_id": settings.youtube_client_id,
        "redirect_uri": youtube_redirect_uri(settings),
        "response_type": "code",
        "scope": settings.youtube_scopes,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(query)}"


def load_youtube_token(settings: Settings) -> YouTubeToken | None:
    path = settings.youtube_token_path
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_at = payload.get("expires_at")
    token_type = payload.get("token_type", "Bearer")
    if not (
        isinstance(access_token, str)
        and isinstance(refresh_token, str)
        and isinstance(expires_at, str)
        and isinstance(token_type, str)
    ):
        return None
    return YouTubeToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=datetime.fromisoformat(expires_at),
        token_type=token_type,
    )


def save_youtube_token(settings: Settings, token: YouTubeToken) -> None:
    path = settings.youtube_token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(token)
    payload["expires_at"] = token.expires_at.isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def youtube_connected(settings: Settings) -> bool:
    return load_youtube_token(settings) is not None


async def exchange_youtube_code(settings: Settings, code: str) -> YouTubeToken:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": youtube_redirect_uri(settings),
            },
        )
    response.raise_for_status()
    return _token_from_response(response, previous_refresh_token="")


async def refresh_youtube_token(settings: Settings, token: YouTubeToken) -> YouTubeToken:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.youtube_client_id,
                "client_secret": settings.youtube_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
            },
        )
    response.raise_for_status()
    return _token_from_response(response, previous_refresh_token=token.refresh_token)


async def get_valid_youtube_token(settings: Settings) -> YouTubeToken | None:
    token = load_youtube_token(settings)
    if token is None:
        return None
    if token.expires_at > datetime.now(UTC) + timedelta(minutes=2):
        return token
    refreshed = await refresh_youtube_token(settings, token)
    save_youtube_token(settings, refreshed)
    return refreshed


async def upload_youtube_video(
    settings: Settings,
    video_path: Path,
    title: str,
    description: str,
    privacy_status: str,
) -> str:
    token = await get_valid_youtube_token(settings)
    if token is None:
        msg = "YouTube account is not connected"
        raise RuntimeError(msg)

    metadata = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    timeout = httpx.Timeout(300.0, connect=30.0, read=300.0, write=300.0)
    headers = {
        "Authorization": f"{token.token_type} {token.access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(video_path.stat().st_size),
        "X-Upload-Content-Type": "video/mp4",
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        init_response = await client.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers=headers,
            json=metadata,
        )
        init_response.raise_for_status()
        upload_location = init_response.headers.get("Location")
        if not upload_location:
            msg = "YouTube did not return an upload URL"
            raise RuntimeError(msg)

        logger.info("YouTube upload started: video_path=%s", video_path)
        upload_response = await client.put(
            upload_location,
            headers={"Content-Type": "video/mp4"},
            content=video_path.read_bytes(),
        )
        upload_response.raise_for_status()

    payload = _json_object(upload_response)
    video_id = payload.get("id")
    if not isinstance(video_id, str) or not video_id:
        msg = "YouTube upload response did not include a video id"
        raise RuntimeError(msg)
    logger.info("YouTube upload completed: video_id=%s", video_id)
    return video_id


def build_youtube_title(job_id: int, caption: str | None) -> str:
    if not caption:
        return f"Video Social Bot #{job_id}"
    first_line = caption.splitlines()[0].strip()
    return first_line[:100] if first_line else f"Video Social Bot #{job_id}"


def _token_from_response(response: httpx.Response, previous_refresh_token: str) -> YouTubeToken:
    payload = _json_object(response)
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token", previous_refresh_token)
    expires_in = payload.get("expires_in")
    token_type = payload.get("token_type", "Bearer")
    if not (
        isinstance(access_token, str)
        and isinstance(refresh_token, str)
        and isinstance(expires_in, int)
        and isinstance(token_type, str)
    ):
        msg = "Invalid YouTube token response"
        raise RuntimeError(msg)
    return YouTubeToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=expires_in),
        token_type=token_type,
    )


def _json_object(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    if not isinstance(payload, dict):
        msg = "Expected JSON object response"
        raise RuntimeError(msg)
    return {str(key): value for key, value in payload.items()}
