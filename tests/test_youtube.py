from datetime import UTC, datetime, timedelta
from pathlib import Path

from video_social_bot.config import Settings
from video_social_bot.youtube import (
    YouTubeToken,
    build_youtube_auth_url,
    build_youtube_title,
    load_youtube_token,
    save_youtube_token,
    youtube_configured,
    youtube_connected,
    youtube_redirect_uri,
)


def test_youtube_configured_requires_client_credentials() -> None:
    assert not youtube_configured(Settings())
    assert youtube_configured(Settings(youtube_client_id="client", youtube_client_secret="secret"))


def test_youtube_redirect_uri_defaults_to_app_base_url() -> None:
    settings = Settings(app_base_url="https://example.com")

    result = youtube_redirect_uri(settings)

    assert result == "https://example.com/integrations/youtube/callback"


def test_build_youtube_auth_url() -> None:
    settings = Settings(
        youtube_client_id="client-id",
        youtube_client_secret="secret",
        youtube_redirect_uri="https://example.com/callback",
    )

    result = build_youtube_auth_url(settings, "state-token")

    assert result.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=client-id" in result
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fcallback" in result
    assert "access_type=offline" in result
    assert "prompt=consent" in result
    assert "state=state-token" in result


def test_youtube_token_roundtrip(tmp_path: Path) -> None:
    settings = Settings(youtube_token_path=tmp_path / "youtube-token.json")
    token = YouTubeToken(
        access_token="access",
        refresh_token="refresh",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )

    save_youtube_token(settings, token)

    loaded = load_youtube_token(settings)
    assert loaded == token
    assert youtube_connected(settings)


def test_build_youtube_title_uses_caption_first_line() -> None:
    result = build_youtube_title(123, "First line\nSecond line")

    assert result == "First line"


def test_build_youtube_title_fallback() -> None:
    result = build_youtube_title(123, "")

    assert result == "Video Social Bot #123"
