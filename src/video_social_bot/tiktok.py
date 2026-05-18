import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

from video_social_bot.config import Settings

logger = logging.getLogger(__name__)

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
INBOX_UPLOAD_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
STATUS_FETCH_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
DEFAULT_CHUNK_SIZE = 10_000_000


@dataclass(frozen=True)
class TikTokToken:
    access_token: str
    refresh_token: str
    expires_at: datetime
    refresh_expires_at: datetime
    open_id: str
    scope: str
    token_type: str = "Bearer"


@dataclass(frozen=True)
class TikTokUploadResult:
    publish_id: str
    status: str


def tiktok_configured(settings: Settings) -> bool:
    return bool(settings.tiktok_client_key and settings.tiktok_client_secret)


def tiktok_redirect_uri(settings: Settings) -> str:
    if settings.tiktok_redirect_uri:
        return settings.tiktok_redirect_uri
    return f"{settings.app_base_url.rstrip('/')}/integrations/tiktok/callback"


def build_tiktok_auth_url(settings: Settings, state: str) -> str:
    query = {
        "client_key": settings.tiktok_client_key,
        "response_type": "code",
        "scope": settings.tiktok_scopes,
        "redirect_uri": tiktok_redirect_uri(settings),
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(query)}"


def load_tiktok_token(settings: Settings) -> TikTokToken | None:
    path = settings.tiktok_token_path
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    return _token_from_stored_payload({str(key): value for key, value in payload.items()})


def save_tiktok_token(settings: Settings, token: TikTokToken) -> None:
    path = settings.tiktok_token_path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(token)
    payload["expires_at"] = token.expires_at.isoformat()
    payload["refresh_expires_at"] = token.refresh_expires_at.isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def tiktok_connected(settings: Settings) -> bool:
    return load_tiktok_token(settings) is not None


async def exchange_tiktok_code(settings: Settings, code: str) -> TikTokToken:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_key": settings.tiktok_client_key,
                "client_secret": settings.tiktok_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": tiktok_redirect_uri(settings),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    response.raise_for_status()
    return _token_from_response(response)


async def refresh_tiktok_token(settings: Settings, token: TikTokToken) -> TikTokToken:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "client_key": settings.tiktok_client_key,
                "client_secret": settings.tiktok_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    response.raise_for_status()
    return _token_from_response(response)


async def get_valid_tiktok_token(settings: Settings) -> TikTokToken | None:
    token = load_tiktok_token(settings)
    if token is None:
        return None
    if token.expires_at > datetime.now(UTC) + timedelta(minutes=2):
        return token
    refreshed = await refresh_tiktok_token(settings, token)
    save_tiktok_token(settings, refreshed)
    return refreshed


async def upload_tiktok_video_to_inbox(
    settings: Settings,
    video_path: Path,
) -> TikTokUploadResult:
    token = await get_valid_tiktok_token(settings)
    if token is None:
        msg = "TikTok account is not connected"
        raise RuntimeError(msg)

    video_size = video_path.stat().st_size
    chunk_size = min(DEFAULT_CHUNK_SIZE, video_size)
    total_chunk_count = max(1, math.ceil(video_size / chunk_size))
    headers = {
        "Authorization": f"{token.token_type} {token.access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0)) as client:
        init_response = await client.post(
            INBOX_UPLOAD_INIT_URL,
            headers=headers,
            json={
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": video_size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": total_chunk_count,
                },
            },
        )
        init_response.raise_for_status()
        init_payload = _json_object(init_response)
        _ensure_tiktok_ok(init_payload)
        data = init_payload.get("data")
        if not isinstance(data, dict):
            msg = "TikTok upload init response missing data"
            raise RuntimeError(msg)
        publish_id = data.get("publish_id")
        upload_url = data.get("upload_url")
        if not isinstance(publish_id, str) or not isinstance(upload_url, str):
            msg = "TikTok upload init response missing publish_id or upload_url"
            raise RuntimeError(msg)

        start = 0
        with video_path.open("rb") as video_file:
            for chunk_index in range(total_chunk_count):
                chunk = video_file.read(chunk_size)
                if not chunk:
                    break
                end = start + len(chunk) - 1
                upload_response = await client.put(
                    upload_url,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {start}-{end}/{video_size}",
                    },
                    content=chunk,
                )
                upload_response.raise_for_status()
                logger.debug(
                    "TikTok upload chunk sent: publish_id=%s chunk=%s/%s",
                    publish_id,
                    chunk_index + 1,
                    total_chunk_count,
                )
                start = end + 1

    logger.info("TikTok inbox upload completed: publish_id=%s", publish_id)
    return TikTokUploadResult(publish_id=publish_id, status="uploaded")


async def fetch_tiktok_publish_status(settings: Settings, publish_id: str) -> str:
    token = await get_valid_tiktok_token(settings)
    if token is None:
        msg = "TikTok account is not connected"
        raise RuntimeError(msg)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            STATUS_FETCH_URL,
            headers={
                "Authorization": f"{token.token_type} {token.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            json={"publish_id": publish_id},
        )
    response.raise_for_status()
    payload = _json_object(response)
    _ensure_tiktok_ok(payload)
    data = payload.get("data")
    if not isinstance(data, dict):
        msg = "TikTok status response missing data"
        raise RuntimeError(msg)
    status = data.get("status")
    return status if isinstance(status, str) else "unknown"


def _token_from_response(response: httpx.Response) -> TikTokToken:
    return _token_from_payload(_json_object(response))


def _token_from_payload(payload: dict[str, object]) -> TikTokToken:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")
    refresh_expires_in = payload.get("refresh_expires_in")
    open_id = payload.get("open_id")
    scope = payload.get("scope")
    token_type = payload.get("token_type", "Bearer")
    if not (
        isinstance(access_token, str)
        and isinstance(refresh_token, str)
        and isinstance(expires_in, (int, float))
        and isinstance(refresh_expires_in, (int, float))
        and isinstance(open_id, str)
        and isinstance(scope, str)
        and isinstance(token_type, str)
    ):
        msg = "Invalid TikTok token response"
        raise RuntimeError(msg)
    return TikTokToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=datetime.now(UTC) + timedelta(seconds=int(expires_in)),
        refresh_expires_at=datetime.now(UTC) + timedelta(seconds=int(refresh_expires_in)),
        open_id=open_id,
        scope=scope,
        token_type=token_type,
    )


def _token_from_stored_payload(payload: dict[str, object]) -> TikTokToken | None:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_at = payload.get("expires_at")
    refresh_expires_at = payload.get("refresh_expires_at")
    open_id = payload.get("open_id")
    scope = payload.get("scope")
    token_type = payload.get("token_type", "Bearer")
    if not (
        isinstance(access_token, str)
        and isinstance(refresh_token, str)
        and isinstance(expires_at, str)
        and isinstance(refresh_expires_at, str)
        and isinstance(open_id, str)
        and isinstance(scope, str)
        and isinstance(token_type, str)
    ):
        return None
    return TikTokToken(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=datetime.fromisoformat(expires_at),
        refresh_expires_at=datetime.fromisoformat(refresh_expires_at),
        open_id=open_id,
        scope=scope,
        token_type=token_type,
    )


def _json_object(response: httpx.Response) -> dict[str, object]:
    payload = response.json()
    if not isinstance(payload, dict):
        msg = "Expected JSON object response"
        raise RuntimeError(msg)
    return {str(key): value for key, value in payload.items()}


def _ensure_tiktok_ok(payload: dict[str, object]) -> None:
    error = payload.get("error")
    if not isinstance(error, dict):
        return
    code = error.get("code")
    if code not in {None, "ok"}:
        message = error.get("message")
        msg = message if isinstance(message, str) and message else str(code)
        raise RuntimeError(msg)
