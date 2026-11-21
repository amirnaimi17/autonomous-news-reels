"""Importance scores for discovered events.

Audience relevance is a gate. Recency, source count, and source class decide
the score only after that gate. A 48–72 hour story still needs a higher score
than a story from today. The weights are fixed so tests can predict them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.news.audience import audience_filter
from app.services.news.editorial import editorial_approves
from app.services.news.source_quality import best_source_quality

_IMPACT_PHRASES = ("central bank", "leitzins", "interest rate", "leitzinsen")
_IMPACT_TOKENS = frozenset(
    {
        "election",
        "war",
        "court",
        "ecb",
        "fed",
        "disaster",
        "killed",
        "sanctions",
        "treaty",
        "parliament",
        "invasion",
        "wahl",
        "krieg",
        "gericht",
        "ezb",
        "sanktionen",
        "bundestag",
        "earthquake",
    }
)
_RECENCY = {"today": 1.0, "yesterday": 0.8, "older": 0.5}
_SOURCES = {0: 0.0, 1: 0.45, 2: 0.75}
_TIER_WEIGHT = {"A": 1.0, "B": 0.8, "C": 0.6, "": 0.0}
_QUALITY_WEIGHT = {"primary": 1.0, "reputable": 0.7, "secondary": 0.35}


@dataclass(frozen=True)
class EventScore:
    """Score and class for one event."""

    score: float
    story_class: str
    band: str
    source_count: int
    impact: bool
    audience_filter: str = "legacy"
    audience_tier: str = ""
    source_quality: str = "secondary"
    matched_terms: tuple[str, ...] = ()


def recency_band(published_at: datetime | None, now: datetime, timezone_name: str) -> str:
    """Classify a publication by the client-local calendar date."""

    if published_at is None:
        return "outside"
    zone = ZoneInfo(timezone_name)
    published_day = published_at.astimezone(zone).date()
    today = now.astimezone(zone).date()
    if published_day == today:
        return "today"
    if published_day == today - timedelta(days=1):
        return "yesterday"
    if published_day < today:
        return "older"
    return "outside"


def has_impact(text: str) -> bool:
    """Return whether the text contains one of the explicit impact terms."""

    lowered = text.lower()
    if any(phrase in lowered for phrase in _IMPACT_PHRASES):
        return True
    tokens = set(re.findall(r"[a-zäöüß]+", lowered))
    return bool(tokens & _IMPACT_TOKENS)


def score_event(
    *,
    band: str,
    source_count: int,
    impact: bool,
    opinion: bool,
    text: str = "",
    source_urls: Sequence[str] = (),
    editorial: Mapping[str, object] | None = None,
) -> EventScore:
    """Score one event. Opinion stays at zero. No audience match cannot be selected."""

    if opinion:
        return EventScore(0.0, "opinion", band, source_count, impact)
    match = audience_filter(text)
    quality = best_source_quality(source_urls)
    recency = _RECENCY.get(band, 0.0)
    sources = _SOURCES.get(source_count, 1.0)
    value = round(
        0.40 * _TIER_WEIGHT.get(match.tier, 0.0)
        + 0.25 * recency
        + 0.20 * sources
        + 0.15 * _QUALITY_WEIGHT[quality],
        4,
    )
    approved = editorial_approves(editorial, source_urls)
    selectable = match.result == "clear" or (match.result == "borderline" and approved)
    recorded_filter = "approved" if match.result == "borderline" and approved else match.result
    if selectable and band == "today" and source_count >= 2 and impact and value >= 0.7:
        story_class = "breaking"
    elif value >= 0.7:
        story_class = "major"
    else:
        story_class = "minor_update"
    return EventScore(
        value,
        story_class,
        band,
        source_count,
        impact,
        recorded_filter,
        match.tier,
        quality,
        match.matched_terms,
    )


def eligible(scored: EventScore, *, minimum: float, older_minimum: float) -> bool:
    """Apply the daily quality bar. Older stories inside the window need a higher score."""

    if scored.audience_filter in {"none", "borderline"}:
        return False
    if scored.story_class in {"opinion", "duplicate"}:
        return False
    if scored.band in {"today", "yesterday"}:
        return scored.score >= minimum
    if scored.band == "older":
        return scored.score >= older_minimum
    return False
