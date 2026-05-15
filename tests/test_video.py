from video_social_bot.config import Settings
from video_social_bot.video import watermark_filter


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
