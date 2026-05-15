import logging
from pathlib import Path

from openai import AsyncOpenAI

from video_social_bot.config import Settings
from video_social_bot.enums import CaptionLanguage

logger = logging.getLogger(__name__)


class TranscriptionClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            msg = "OPENAI_API_KEY is required for Whisper transcription"
            raise RuntimeError(msg)
        self._settings = settings
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def transcribe(self, audio_path: Path) -> str:
        logger.info("Starting Whisper transcription: %s", audio_path)
        with audio_path.open("rb") as audio_file:
            result = await self._client.audio.transcriptions.create(
                model=self._settings.whisper_model,
                file=audio_file,
                response_format="text",
            )
        transcript = str(result).strip()
        logger.info("Whisper transcription complete: chars=%s", len(transcript))
        return transcript


class CaptionClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key:
            msg = "LLM_API_KEY is required for caption generation"
            raise RuntimeError(msg)
        self._settings = settings
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
        )

    async def generate_caption(
        self,
        transcript: str,
        language: CaptionLanguage,
        extra_context: str = "",
    ) -> str:
        language_name = "Russian" if language == CaptionLanguage.RU else "English"
        logger.info(
            "Generating caption: model=%s language=%s transcript_chars=%s",
            self._settings.llm_model,
            language,
            len(transcript),
        )
        headers: dict[str, str] = {}
        if self._settings.llm_http_referer:
            headers["HTTP-Referer"] = self._settings.llm_http_referer
        if self._settings.llm_app_title:
            headers["X-Title"] = self._settings.llm_app_title

        response = await self._client.chat.completions.create(
            model=self._settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write natural short-video captions for YouTube Shorts, "
                        "TikTok and Instagram Reels. Do not make medical, financial or "
                        "legal claims. Return one ready-to-publish caption with 3-8 "
                        "relevant hashtags."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Language: {language_name}\n"
                        f"Transcript:\n{transcript or '[no speech detected]'}\n\n"
                        f"Extra context:\n{extra_context or '[none]'}"
                    ),
                },
            ],
            extra_headers=headers or None,
            temperature=0.8,
        )
        choice = response.choices[0]
        content = choice.message.content
        if not content:
            msg = "LLM returned an empty caption"
            raise RuntimeError(msg)
        caption = content.strip()
        logger.info("Caption generated: chars=%s", len(caption))
        return caption
