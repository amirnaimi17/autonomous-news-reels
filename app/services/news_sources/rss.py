"""RSS and Atom reader.

Feeds are whatever the caller configured. This module contains no feed URLs.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.request import Request, urlopen

from app.core.config import NewsSourceConfig
from app.schemas.news import DiscoveredArticle
from app.schemas.workflow import ResearchResult, SourceFailure
from app.services.text import plain_text


class RssTransport(Protocol):
    """HTTP GET used by the RSS client. Tests supply a fake."""

    def fetch(self, url: str) -> bytes:
        """Return the raw feed body."""


class UrllibTransport:
    """Standard-library fetch with the configured timeout and user agent."""

    def __init__(self, *, timeout: float, user_agent: str) -> None:
        self._timeout = timeout
        self._user_agent = user_agent

    def fetch(self, url: str) -> bytes:
        request = Request(url, headers={"User-Agent": self._user_agent})
        with urlopen(request, timeout=self._timeout) as response:  # noqa: S310
            return response.read()


class RssNewsSource:
    """Collect configured feeds. One failure does not drop the other feeds."""

    name = "rss"

    def __init__(self, sources: tuple[NewsSourceConfig, ...] | list[NewsSourceConfig], transport: RssTransport) -> None:
        self._sources = tuple(sources)
        self._transport = transport

    def fetch(self, *, window_start: datetime, window_end: datetime) -> ResearchResult:
        articles: list[DiscoveredArticle] = []
        failures: list[SourceFailure] = []
        start = window_start.astimezone(timezone.utc)
        end = window_end.astimezone(timezone.utc)
        for source in self._sources:
            try:
                payload = self._transport.fetch(source.url)
                parsed = parse_feed(payload, source)
            except Exception as exc:
                failures.append(SourceFailure(source_name=source.name, error=str(exc) or exc.__class__.__name__))
                continue
            for article in parsed:
                if article.published_at is None:
                    continue
                moment = article.published_at.astimezone(timezone.utc)
                if start <= moment <= end:
                    articles.append(article)
        return ResearchResult(articles=articles, failures=failures)


def parse_feed(payload: bytes, source: NewsSourceConfig) -> list[DiscoveredArticle]:
    """Parse an RSS or Atom document into discovered articles."""

    root = ET.fromstring(payload)
    nodes = [element for element in root.iter() if _local(element.tag) in {"item", "entry"}]
    articles: list[DiscoveredArticle] = []
    for node in nodes:
        title = plain_text(_text(node, "title"))
        link = _link(node)
        if not title or not link:
            continue
        summary = plain_text(_text(node, "description") or _text(node, "summary") or _text(node, "content"))
        published = _published(node)
        articles.append(
            DiscoveredArticle(
                source_name=source.name,
                source_url=link,
                canonical_url=link,
                title=title,
                summary=summary,
                published_at=published,
                language=source.language,
            )
        )
    return articles


def parse_timestamp(value: str) -> datetime | None:
    """Parse an RFC 822 or ISO timestamp. Naive values are treated as UTC."""

    text = value.strip()
    if not text:
        return None
    iso = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        parsed = None
    if parsed is None:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _published(node: ET.Element) -> datetime | None:
    for name in ("pubdate", "published", "updated", "date"):
        raw = _text(node, name)
        if raw:
            parsed = parse_timestamp(raw)
            if parsed is not None:
                return parsed
    return None


def _text(node: ET.Element, name: str) -> str:
    for child in list(node):
        if _local(child.tag) == name and child.text:
            return child.text
    return ""


def _link(node: ET.Element) -> str:
    for child in list(node):
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if child.text and child.text.strip():
            return child.text.strip()
    return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()
