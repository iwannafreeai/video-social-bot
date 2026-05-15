from video_social_bot.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()

    assert settings.max_upload_mb == 100
    assert settings.file_ttl_hours == 24
    assert settings.llm_base_url == "https://openrouter.ai/api/v1"
    assert settings.log_level == "INFO"
    assert settings.watermark_position == "bottom-right"
