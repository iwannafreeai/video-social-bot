from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Video Social Bot"
    app_base_url: str = "http://127.0.0.1:8000"
    secret_key: str = "change-me"
    log_level: str = "INFO"

    telegram_bot_token: str = ""
    admin_username: str = "admin"
    admin_password: str = "change-me"

    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    storage_dir: Path = Path("./storage")
    max_upload_mb: int = 100
    file_ttl_hours: int = 24
    web_worker_enabled: bool = False

    openai_api_key: str = ""
    whisper_model: str = "whisper-1"

    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-4o-mini"
    llm_http_referer: str = ""
    llm_app_title: str = "Video Social Bot"

    ffmpeg_preset: str = "veryfast"
    output_crf: int = Field(default=28, ge=18, le=35)
    output_audio_bitrate: str = "96k"
    watermark_text: str = ""
    watermark_font_size: int = Field(default=42, ge=12, le=120)
    watermark_opacity: float = Field(default=0.35, ge=0, le=1)
    watermark_position: str = "bottom-right"
    subtitles_enabled: bool = True
    burn_subtitles: bool = False
    subtitle_max_chars: int = Field(default=42, ge=20, le=80)
    subtitle_font_size: int = Field(default=44, ge=18, le=90)
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = ""
    youtube_scopes: str = "https://www.googleapis.com/auth/youtube.upload"
    youtube_token_path: Path = Path("./data/youtube-token.json")
    youtube_default_privacy_status: str = "private"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @field_validator("max_upload_mb")
    @classmethod
    def validate_max_upload_mb(cls, value: int) -> int:
        if value < 1:
            msg = "MAX_UPLOAD_MB must be positive"
            raise ValueError(msg)
        return value

    @field_validator("file_ttl_hours")
    @classmethod
    def validate_file_ttl_hours(cls, value: int) -> int:
        if value < 1:
            msg = "FILE_TTL_HOURS must be positive"
            raise ValueError(msg)
        return value

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            msg = "LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL"
            raise ValueError(msg)
        return normalized

    @field_validator("watermark_position")
    @classmethod
    def validate_watermark_position(cls, value: str) -> str:
        if value not in {"top-left", "top-right", "bottom-left", "bottom-right"}:
            msg = "WATERMARK_POSITION must be top-left, top-right, bottom-left, or bottom-right"
            raise ValueError(msg)
        return value

    @field_validator("youtube_default_privacy_status")
    @classmethod
    def validate_youtube_default_privacy_status(cls, value: str) -> str:
        if value not in {"private", "unlisted", "public"}:
            msg = "YOUTUBE_DEFAULT_PRIVACY_STATUS must be private, unlisted, or public"
            raise ValueError(msg)
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
