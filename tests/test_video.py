from video_social_bot.config import Settings
from video_social_bot.models import Client
from video_social_bot.video import resolve_watermark_settings, watermark_filter


def test_watermark_filter_disabled_by_default() -> None:
    settings = Settings()

    assert watermark_filter(settings) is None


def test_watermark_filter_enabled() -> None:
    settings = Settings(watermark_text="@brand", watermark_position="top-left")

    result = watermark_filter(settings)

    assert result is not None
    assert "drawtext=" in result
    assert "@brand" in result
    assert "x=40:y=40" in result


def test_client_watermark_overrides_global_settings() -> None:
    settings = Settings(watermark_text="@global", watermark_position="top-left")
    client = Client(
        name="Client",
        watermark_text="@client",
        watermark_position="bottom-left",
        watermark_opacity=60,
        watermark_font_size=50,
    )

    watermark = resolve_watermark_settings(settings, client)
    result = watermark_filter(settings, client)

    assert watermark is not None
    assert watermark.text == "@client"
    assert watermark.opacity == 0.6
    assert result is not None
    assert "@client" in result
    assert "fontsize=50" in result
    assert "x=40:y=h-th-40" in result


def test_global_watermark_used_when_client_branding_empty() -> None:
    settings = Settings(watermark_text="@global")
    client = Client(name="Client")

    watermark = resolve_watermark_settings(settings, client)

    assert watermark is not None
    assert watermark.text == "@global"
