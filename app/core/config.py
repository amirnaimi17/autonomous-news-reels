"""Process configuration.

Environment variables and an optional `.env` file are the only sources.
The default client id is the seam for later per-account settings.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ENV_VARS: tuple[str, ...] = (
    "APP_ENV",
    "CLIENT_ID",
    "CLIENT_NAME",
    "TIMEZONE",
    "DAILY_REEL_LIMIT",
    "PRODUCTION_SLOTS",
    "CATCH_UP_MISSED_SLOTS",
    "NEWS_WINDOW_HOURS",
    "MIN_IMPORTANCE_SCORE",
    "FAIL_CLOSED_DEDUPLICATION",
    "TITLE_JACCARD_DUPLICATE_THRESHOLD",
    "SUMMARY_JACCARD_DUPLICATE_THRESHOLD",
    "ENTITY_JACCARD_DUPLICATE_THRESHOLD",
    "SIMHASH_HAMMING_THRESHOLD",
    "NEWS_PROVIDER",
    "NEWS_SOURCES",
    "NEWS_SOURCES_FILE",
    "STOPWORDS_DIR",
    "ENTITY_ALIASES_FILE",
    "TRANSLATION_PROVIDER",
    "OLDER_WINDOW_MIN_IMPORTANCE",
    "HTTP_TIMEOUT_SECONDS",
    "HTTP_USER_AGENT",
    "DATABASE_PATH",
    "OUTPUT_DIR",
    "LOG_LEVEL",
    "LOG_FILE",
    "VIDEO_WIDTH",
    "VIDEO_HEIGHT",
    "VIDEO_ENCODER",
    "FFMPEG_BIN",
    "MIN_REEL_SECONDS",
    "MAX_REEL_SECONDS",
    "IMAGE_PROVIDER",
    "TTS_PROVIDER",
    "NOTIFICATION_PROVIDER",
    "LLM_PROVIDER",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "OPENAI_API_KEY",
    "INSTAGRAM_PUBLISH_ENABLED",
    "SLOT_STALE_SECONDS",
    "LOCK_TTL_SECONDS",
    "MAX_GENERATION_ATTEMPTS",
)


class NewsSourceConfig(BaseModel):
    """One configured headline source."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    url: str
    language: str
    kind: Literal["rss"] = "rss"

    @field_validator("language")
    @classmethod
    def language_code(cls, value: str) -> str:
        lowered = value.strip().lower()
        if not lowered.isalpha() or not 2 <= len(lowered) <= 3:
            raise ValueError("language must be a 2 or 3 letter code such as en or de")
        return lowered

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"invalid source url: {value}")
        return value


def _coerce_source(value: object) -> NewsSourceConfig:
    if isinstance(value, NewsSourceConfig):
        return value
    if isinstance(value, dict):
        return NewsSourceConfig.model_validate(value)
    raise ValueError("each news source must be an object with name and url")


class Settings(BaseSettings):
    """Runtime settings for one deployment.

    One deployment serves one client in the MVP. CLIENT_ID is stored on every
    row so a later multi-client scheduler can share this database.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: Literal["development", "test", "production"] = "development"
    client_id: str = "default"
    client_name: str = "Default"
    timezone: str = "Europe/Berlin"
    daily_reel_limit: int = Field(default=3, ge=0, le=24)
    production_slots: tuple[str, ...] = ("09:00", "14:00", "19:00")
    catch_up_missed_slots: bool = True
    news_window_hours: int = Field(default=72, ge=1, le=168)
    min_importance_score: float = Field(default=0.55, ge=0, le=1)
    fail_closed_deduplication: bool = True
    title_jaccard_duplicate_threshold: float = Field(default=0.72, ge=0, le=1)
    summary_jaccard_duplicate_threshold: float = Field(default=0.40, ge=0, le=1)
    entity_jaccard_duplicate_threshold: float = Field(default=0.50, ge=0, le=1)
    simhash_hamming_threshold: int = Field(default=8, ge=0, le=64)
    news_provider: Literal["rss", "static"] = "rss"
    news_sources_file: Path | None = None
    news_sources: Annotated[tuple[NewsSourceConfig, ...], NoDecode] = ()
    stopwords_dir: Path = Path("config/stopwords")
    entity_aliases_file: Path | None = None
    translation_provider: Literal["none"] = "none"
    older_window_min_importance: float = Field(default=0.75, ge=0, le=1)
    http_timeout_seconds: float = Field(default=20, gt=0, le=120)
    http_user_agent: str = "AutonomousNewsReels/0.1"
    database_path: Path = Path("data/news_reels.db")
    output_dir: Path = Path("storage")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_file: Path | None = None
    video_width: int = 1080
    video_height: int = 1920
    video_encoder: Literal["auto", "h264_nvenc", "libx264"] = "auto"
    ffmpeg_bin: str = "ffmpeg"
    min_reel_seconds: float = Field(default=8, gt=0)
    max_reel_seconds: float = Field(default=90, gt=0)
    image_provider: Literal["solid"] = "solid"
    tts_provider: Literal["silent"] = "silent"
    notification_provider: Literal["log", "telegram"] = "log"
    llm_provider: Literal["extractive"] = "extractive"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    openai_api_key: str = ""
    instagram_publish_enabled: bool = False
    slot_stale_seconds: int = Field(default=2700, ge=60)
    lock_ttl_seconds: int = Field(default=900, ge=30)
    max_generation_attempts: int = Field(default=3, ge=1, le=10)

    @field_validator("client_id")
    @classmethod
    def client_id_token(cls, value: str) -> str:
        if not value or len(value) > 64:
            raise ValueError("client_id must be 1 to 64 characters")
        allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-_")
        if value[0] not in set("abcdefghijklmnopqrstuvwxyz0123456789") or any(
            char not in allowed for char in value
        ):
            raise ValueError("client_id must be a lowercase slug")
        return value

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {value}") from exc
        return value

    @field_validator("production_slots", mode="before")
    @classmethod
    def parse_slots(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",") if part.strip()]
        elif isinstance(value, (list, tuple)):
            items = [str(part).strip() for part in value]
        else:
            raise ValueError("production slots must be comma-separated HH:MM times")
        normalized: list[str] = []
        for item in items:
            from datetime import datetime

            try:
                parsed = datetime.strptime(item, "%H:%M")
            except ValueError as exc:
                raise ValueError(f"invalid production slot: {item}") from exc
            normalized.append(parsed.strftime("%H:%M"))
        if not normalized:
            raise ValueError("at least one production slot is required")
        if len(set(normalized)) != len(normalized):
            raise ValueError("production slots must be unique")
        normalized.sort()
        return tuple(normalized)

    @field_validator("news_sources", mode="before")
    @classmethod
    def parse_sources(cls, value: object) -> tuple[NewsSourceConfig, ...]:
        if value is None or value == "":
            return ()
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return ()
            if not text.startswith("["):
                raise ValueError(
                    "NEWS_SOURCES must be a JSON list of objects with name, url, and language"
                )
            parsed = json.loads(text)
            if not isinstance(parsed, list):
                raise ValueError("NEWS_SOURCES JSON must be a list")
            return tuple(_coerce_source(item) for item in parsed)
        if isinstance(value, tuple) and all(isinstance(item, NewsSourceConfig) for item in value):
            return value
        if isinstance(value, (list, tuple)):
            return tuple(_coerce_source(item) for item in value)
        raise ValueError("NEWS_SOURCES must be a JSON list of objects with name, url, and language")

    @field_validator("video_width", "video_height")
    @classmethod
    def even_dimension(cls, value: int) -> int:
        if value < 2 or value > 4320 or value % 2 != 0:
            raise ValueError("video dimensions must be even numbers from 2 to 4320")
        return value

    @field_validator("max_reel_seconds")
    @classmethod
    def duration_order(cls, value: float, info: ValidationInfo) -> float:
        minimum = info.data.get("min_reel_seconds", 8)
        if value <= minimum:
            raise ValueError("max_reel_seconds must be greater than min_reel_seconds")
        return value

    @property
    def slot_limit(self) -> int:
        """Reels allowed today: the configured cap, bounded by the slot count."""

        return min(self.daily_reel_limit, len(self.production_slots))

    def redacted(self) -> dict[str, object]:
        """Settings safe to print. Tokens are masked."""

        data = self.model_dump(mode="json")
        for key in ("telegram_bot_token", "openai_api_key"):
            if data.get(key):
                data[key] = "***"
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process settings. The result is cached."""

    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings. Tests call this after changing the environment."""

    get_settings.cache_clear()
