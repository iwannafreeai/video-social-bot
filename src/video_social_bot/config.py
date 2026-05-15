from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Video Social Bot"
    app_base_url: str = "http://127.0.0.1:8000"
    secret_key: str = "change-me"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
