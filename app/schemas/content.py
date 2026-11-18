"""Structured reel content passed between agents."""

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class GenerationState(str, Enum):
    """Lifecycle of one reel. The database rejects any other value."""

    DISCOVERED = "DISCOVERED"
    SELECTED = "SELECTED"
    SCRIPT_GENERATED = "SCRIPT_GENERATED"
    IMAGES_GENERATED = "IMAGES_GENERATED"
    AUDIO_GENERATED = "AUDIO_GENERATED"
    VIDEO_RENDERED = "VIDEO_RENDERED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class SlotStatus(str, Enum):
    """Lifecycle of one production slot on a local calendar day."""

    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class SourceReference(BaseModel):
    """A source the narration is allowed to rely on."""

    name: str = Field(min_length=1)
    url: str
    published_at: str | None = None

    @field_validator("url")
    @classmethod
    def http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("source url must start with http:// or https://")
        return value


class SlideScript(BaseModel):
    """Copy and visual direction for one vertical slide."""

    index: int = Field(ge=1)
    headline: str = Field(min_length=1, max_length=140)
    on_screen_text: str = Field(min_length=1, max_length=280)
    narration: str = Field(min_length=1)
    visual_brief: str = Field(min_length=1)
    source_urls: list[str] = Field(min_length=1)


class NewsScript(BaseModel):
    """Script contract. Slide narrations are the only spoken words."""

    event_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    language: str = Field(default="en", min_length=2, max_length=16)
    slides: list[SlideScript] = Field(min_length=1, max_length=6)
    full_narration: str = Field(min_length=1)
    sources: list[SourceReference] = Field(min_length=1)
    factual_claims: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def slides_are_ordered_and_narration_matches(self) -> "NewsScript":
        indexes = [slide.index for slide in self.slides]
        if indexes != list(range(1, len(self.slides) + 1)):
            raise ValueError("slide indexes must run from 1 to n in order")
        spoken = " ".join(" ".join(slide.narration.split()) for slide in self.slides)
        if " ".join(self.full_narration.split()) != spoken:
            raise ValueError("full_narration must be the slide narrations joined in order")
        return self


class GeneratedImage(BaseModel):
    """One slide image written by an image provider."""

    slide_index: int = Field(ge=1)
    path: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    provider: str = Field(min_length=1)


class GeneratedSpeech(BaseModel):
    """Narration audio written by a TTS provider."""

    path: str = Field(min_length=1)
    duration_seconds: float = Field(gt=0)
    provider: str = Field(min_length=1)
    sample_rate: int = Field(gt=0)
