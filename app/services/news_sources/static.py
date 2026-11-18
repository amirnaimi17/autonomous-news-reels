"""In-memory news source for tests and manual fixtures."""

from datetime import datetime, timezone

from app.schemas.news import DiscoveredArticle
from app.schemas.workflow import ResearchResult


class StaticNewsSource:
    """Return the articles it was given when they fall inside the window."""

    name = "static"

    def __init__(self, articles: tuple[DiscoveredArticle, ...] | list[DiscoveredArticle]) -> None:
        self._articles = tuple(articles)

    def fetch(self, *, window_start: datetime, window_end: datetime) -> ResearchResult:
        start = _utc(window_start)
        end = _utc(window_end)
        kept = [
            article
            for article in self._articles
            if article.published_at is not None and start <= _utc(article.published_at) <= end
        ]
        return ResearchResult(articles=kept)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("window bounds must be timezone-aware")
    return value.astimezone(timezone.utc)
