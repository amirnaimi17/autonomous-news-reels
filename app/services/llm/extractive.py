"""Extractive script fallback.

This provider copies sentences from the supplied article. It does not call a
model and it does not add facts to fill a four-slide target.
"""

from __future__ import annotations

import re

from app.schemas.content import NewsScript, SlideScript, SourceReference
from app.schemas.workflow import ScriptRequest, ScriptResult
from app.services.grounding import require_grounded_numbers
from app.services.text import plain_text

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def build_extractive_script(request: ScriptRequest, *, target_slides: int = 4) -> ScriptResult:
    """Build a script whose spoken words all come from the request text."""

    if target_slides < 1 or target_slides > 6:
        raise ValueError("target_slides must be from 1 to 6")
    title = plain_text(request.title)
    summary = plain_text(request.summary)
    if not title:
        raise ValueError("script request has an empty title")
    sentences = _sentences(summary) or [title]
    groups = _chunk(sentences, min(target_slides, len(sentences)))
    slides: list[SlideScript] = []
    for index, group in enumerate(groups, start=1):
        narration = " ".join(group)
        headline_source = title if index == 1 else group[0]
        slides.append(
            SlideScript(
                index=index,
                headline=_shorten(headline_source, 140),
                on_screen_text=_shorten(narration, 280),
                narration=narration,
                visual_brief=(
                    "Typographic news card. Render only the headline text. "
                    "Do not depict people, places, or events."
                ),
                source_urls=[request.source_url],
            )
        )
    full_narration = " ".join(slide.narration for slide in slides)
    published = request.published_at.isoformat() if request.published_at is not None else None
    script = NewsScript(
        event_id=request.event_id,
        title=title,
        language=request.language,
        slides=slides,
        full_narration=full_narration,
        sources=[SourceReference(name=request.source_name, url=request.source_url, published_at=published)],
        factual_claims=sentences,
    )
    require_grounded_numbers(script.full_narration, f"{title} {summary}".strip())
    return ScriptResult(script=script, provider="extractive")


def _sentences(text: str) -> list[str]:
    if not text:
        return []
    return [part.strip() for part in _SENTENCE.split(text) if part.strip()]


def _chunk(items: list[str], groups: int) -> list[list[str]]:
    count, extra = divmod(len(items), groups)
    chunks: list[list[str]] = []
    start = 0
    for index in range(groups):
        take = count + (1 if index < extra else 0)
        chunks.append(items[start : start + take])
        start += take
    return chunks


def _shorten(text: str, limit: int) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= limit:
        return cleaned
    trimmed = cleaned[: limit - 1].rsplit(" ", 1)[0].rstrip(".,;:")
    if len(trimmed) < 8:
        trimmed = cleaned[: limit - 1].rstrip()
    return f"{trimmed}…"
