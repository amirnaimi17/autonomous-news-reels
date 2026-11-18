"""Factories and fixed clocks for repository tests."""

from datetime import datetime, timedelta, timezone

from app.database.models import ArticleInput, EventInput

NOW = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
STALE = timedelta(minutes=45)


def article_input(**overrides: object) -> ArticleInput:
    data: dict[str, object] = {
        "client_id": "default",
        "source_name": "BBC World",
        "source_url": "https://www.bbc.com/news/world-1?utm_source=rss",
        "canonical_url": "https://www.bbc.com/news/world-1?utm_source=rss",
        "title": "Central bank holds rates",
        "normalized_title": "central bank holds rates",
        "title_fingerprint": "rates-fingerprint",
        "summary": "The central bank held rates at 4.5 percent.",
        "published_at": "2026-11-18T07:00:00+00:00",
    }
    data.update(overrides)
    return ArticleInput(**data)  # type: ignore[arg-type]


def event_input(**overrides: object) -> EventInput:
    data: dict[str, object] = {
        "client_id": "default",
        "event_fingerprint": "event-rates",
        "block_key": "central",
        "title": "Central bank holds rates",
        "normalized_title": "central bank holds rates",
        "title_fingerprint": "rates-fingerprint",
        "summary": "The central bank held rates at 4.5 percent.",
        "first_published_at": "2026-11-18T07:00:00+00:00",
        "entities": ("Central Bank",),
    }
    data.update(overrides)
    return EventInput(**data)  # type: ignore[arg-type]
