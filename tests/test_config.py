from video_social_bot.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()

    assert settings.max_upload_mb == 100
    assert settings.file_ttl_hours == 24
    assert settings.llm_base_url == "https://openrouter.ai/api/v1"
    assert settings.log_level == "INFO"
    assert settings.watermark_position == "bottom-right"
    assert settings.output_width == 1080
    assert settings.output_height == 1920
    assert settings.audio_normalize is True


def test_output_dimensions_must_be_even() -> None:
    try:
        Settings(output_width=721)
    except ValueError as exc:
        assert "Output dimensions must be even" in str(exc)
    else:
        raise AssertionError("Expected odd output_width to fail")
