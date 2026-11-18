"""News records exchanged by the research and selection agents."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.content import GenerationState


class DiscoveredArticle(BaseModel):
    """A story as returned by a news source, before it is stored."""

    source_name: str = Field(min_length=1)
    source_url: str
    canonical_url: str
    title: str = Field(min_length=1)
    summary: str = ""
    published_at: datetime | None = None
    language: str | None = None
    image_url: str | None = None

    @field_validator("source_url", "canonical_url")
    @classmethod
    def http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value

    @field_validator("published_at")
    @classmethod
    def aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.tzinfo.utcoffset(value) is None):
            raise ValueError("published_at must include a timezone")
        return value


class KnownEvent(BaseModel):
    """Persisted event history handed to the pure selection agent."""

    event_id: str
    title: str
    normalized_title: str
    title_fingerprint: str
    summary: str
    entities: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    state: GenerationState
    published_at: datetime | None = None
    semantic_fingerprint: str | None = None


class CandidateArticle(BaseModel):
    """Stored article plus the fields required for duplicate comparison."""

    article_id: str
    event_id: str | None = None
    source_name: str
    canonical_url: str
    title: str
    normalized_title: str
    title_fingerprint: str
    summary: str
    published_at: datetime | None = None
    entities: list[str] = Field(default_factory=list)
    simhash: str | None = None


class Rejection(BaseModel):
    """Why a candidate was not selected. Used in shortage notifications."""

    event_id: str | None = None
    canonical_url: str | None = None
    reason: str = Field(min_length=1)
