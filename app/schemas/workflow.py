"""Request and result models for each orchestrator step.

Agents accept and return these models. They do not return free-form plans.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import NewsSourceConfig
from app.schemas.content import GeneratedImage, GeneratedSpeech, NewsScript
from app.schemas.news import CandidateArticle, DiscoveredArticle, KnownEvent, Rejection

StoryClass = Literal["breaking", "major", "minor_update", "opinion", "duplicate"]


class SourceFailure(BaseModel):
    source_name: str
    error: str = Field(min_length=1)


class ResearchRequest(BaseModel):
    client_id: str
    window_start: datetime
    window_end: datetime
    sources: list[NewsSourceConfig] = Field(min_length=1)


class ResearchResult(BaseModel):
    articles: list[DiscoveredArticle] = Field(default_factory=list)
    failures: list[SourceFailure] = Field(default_factory=list)


class SelectionRequest(BaseModel):
    """Everything the selector needs. It does not query the database itself."""

    client_id: str
    now: datetime
    window_start: datetime
    production_date: str
    slot_key: str
    min_importance_score: float = Field(ge=0, le=1)
    articles: list[CandidateArticle] = Field(default_factory=list)
    known_events: list[KnownEvent] = Field(default_factory=list)
    fail_closed_deduplication: bool = True
    title_jaccard_duplicate_threshold: float = Field(default=0.72, ge=0, le=1)
    summary_jaccard_duplicate_threshold: float = Field(default=0.40, ge=0, le=1)
    entity_jaccard_duplicate_threshold: float = Field(default=0.50, ge=0, le=1)
    simhash_hamming_threshold: int = Field(default=8, ge=0, le=64)


class SelectionResult(BaseModel):
    selected_event_id: str | None = None
    importance_score: float | None = Field(default=None, ge=0, le=1)
    story_class: StoryClass | None = None
    explanation: str = Field(min_length=1)
    rejections: list[Rejection] = Field(default_factory=list)
    shortage_reason: str | None = None


class ScriptRequest(BaseModel):
    event_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = ""
    source_name: str = Field(min_length=1)
    source_url: str
    published_at: datetime | None = None
    language: str = "en"

    @field_validator("source_url")
    @classmethod
    def http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("source_url must start with http:// or https://")
        return value


class ScriptResult(BaseModel):
    script: NewsScript
    provider: str


class SlideVisualRequest(BaseModel):
    slide_index: int = Field(ge=1)
    headline: str = Field(min_length=1)
    visual_brief: str = Field(min_length=1)
    output_path: str = Field(min_length=1)


class ImageBatchRequest(BaseModel):
    content_id: str
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    slides: list[SlideVisualRequest] = Field(min_length=1)


class ImageBatchResult(BaseModel):
    images: list[GeneratedImage] = Field(min_length=1)


class VoiceRequest(BaseModel):
    content_id: str
    narration: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    voice: str | None = None


class VoiceResult(BaseModel):
    speech: GeneratedSpeech


class VideoRenderRequest(BaseModel):
    content_id: str
    width: int
    height: int
    image_paths: list[str] = Field(min_length=1)
    audio_path: str
    audio_duration_seconds: float = Field(gt=0)
    output_path: str
    encoder: Literal["h264_nvenc", "libx264"]


class VideoRenderResult(BaseModel):
    video_path: str
    width: int
    height: int
    duration_seconds: float
    video_codec: str
    audio_codec: str


class NotificationRequest(BaseModel):
    client_id: str
    headline: str = Field(min_length=1)
    status: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    video_path: str | None = None


class NotificationResult(BaseModel):
    provider: str
    delivery_status: Literal["SENT", "FAILED"]
    detail: str
