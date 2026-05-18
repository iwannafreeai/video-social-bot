from datetime import UTC, datetime, timedelta
from pathlib import Path

from video_social_bot.config import Settings
from video_social_bot.tiktok import (
    TikTokToken,
    build_tiktok_auth_url,
    load_tiktok_token,
    save_tiktok_token,
    tiktok_configured,
    tiktok_connected,
    tiktok_redirect_uri,
)


def test_tiktok_configured_requires_client_credentials() -> None:
    assert not tiktok_configured(Settings())
    assert tiktok_configured(Settings(tiktok_client_key="key", tiktok_client_secret="secret"))


def test_tiktok_redirect_uri_defaults_to_app_base_url() -> None:
    settings = Settings(app_base_url="https://example.com")

    result = tiktok_redirect_uri(settings)

    assert result == "https://example.com/integrations/tiktok/callback"


def test_build_tiktok_auth_url() -> None:
    settings = Settings(
        tiktok_client_key="client-key",
        tiktok_client_secret="secret",
        tiktok_redirect_uri="https://example.com/tiktok",
    )

    result = build_tiktok_auth_url(settings, "state-token")

    assert result.startswith("https://www.tiktok.com/v2/auth/authorize/?")
    assert "client_key=client-key" in result
    assert "response_type=code" in result
    assert "scope=video.upload" in result
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Ftiktok" in result
    assert "state=state-token" in result


def test_tiktok_token_roundtrip(tmp_path: Path) -> None:
    settings = Settings(tiktok_token_path=tmp_path / "tiktok-token.json")
    token = TikTokToken(
        access_token="access",
        refresh_token="refresh",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        refresh_expires_at=datetime.now(UTC) + timedelta(days=30),
        open_id="open-id",
        scope="video.upload",
    )

    save_tiktok_token(settings, token)

    loaded = load_tiktok_token(settings)
    assert loaded == token
    assert tiktok_connected(settings)
