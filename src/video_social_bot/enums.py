from enum import StrEnum


class CaptionLanguage(StrEnum):
    RU = "ru"
    EN = "en"


class JobStatus(StrEnum):
    NEW = "new"
    WAITING_LANGUAGE = "waiting_language"
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class UploadSource(StrEnum):
    TELEGRAM = "telegram"
    DASHBOARD = "dashboard"
