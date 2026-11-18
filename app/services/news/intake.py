"""Store discovered articles, cluster them, and fill today's selection ranks.

This path never reserves a production slot and never writes generated content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.exceptions import ArticleAlreadyLinkedError, ConfigurationError, DuplicateEventError
from app.core.time import production_date, utc_iso
from app.database.models import ArticleInput, EventInput, EventSelection, SelectionCandidate
from app.database.repository import NewsReelsRepository
from app.schemas.news import DiscoveredArticle
from app.schemas.workflow import SourceFailure
from app.services.dedup.cluster import (
    ClusterText,
    MatchThresholds,
    WorkingCluster,
    assign_articles,
)
from app.services.dedup.fingerprints import (
    block_key,
    normalize_headline,
    simhash64,
    title_fingerprint,
)
from app.services.dedup.language import (
    canonical_entities,
    is_opinion,
    load_aliases,
    load_stopwords,
)
from app.services.dedup.url import canonicalize_url
from app.services.news.scoring import eligible, has_impact, recency_band, score_event
from app.services.news.selection import RankedEvent, order_events
from app.services.news.sources import configured_news_sources
from app.services.translation.base import NoneTranslator, Translator

FUTURE_SKEW = timedelta(minutes=15)
_LIMITATION = (
    "Cross-language matching without a translator is an entity-and-number hint. "
    "It is not reliable multilingual deduplication."
)


@dataclass(frozen=True)
class IntakeReport:
    """What one discovery run stored and selected."""

    selections: tuple[EventSelection, ...]
    unfilled: int
    failures: tuple[SourceFailure, ...]
    articles_seen: int
    translation_provider: str
    limitation: str | None


def run_intake(
    settings: Settings,
    repository: NewsReelsRepository,
    *,
    now: datetime,
    translator: Translator | None = None,
    source: object | None = None,
) -> IntakeReport:
    """Fetch, persist, score, and fill the remaining ranks for the local day."""

    active_translator = translator if translator is not None else NoneTranslator()
    news_source = source if source is not None else _configured_source(settings)
    window_start = now - timedelta(hours=settings.news_window_hours)
    window_end = now + FUTURE_SKEW
    result = news_source.fetch(window_start=window_start, window_end=window_end)
    stopwords = load_stopwords(settings.stopwords_dir)
    aliases = load_aliases(settings.entity_aliases_file)
    thresholds = MatchThresholds(
        title_jaccard=settings.title_jaccard_duplicate_threshold,
        summary_jaccard=settings.summary_jaccard_duplicate_threshold,
        entity_jaccard=settings.entity_jaccard_duplicate_threshold,
        simhash_hamming=settings.simhash_hamming_threshold,
        fail_closed=settings.fail_closed_deduplication,
    )
    articles = [
        article
        for article in result.articles
        if _inside_window(article, window_start, window_end)
    ]
    _persist_articles(
        repository,
        settings=settings,
        articles=articles,
        now=now,
        stopwords=stopwords,
        aliases=aliases,
        thresholds=thresholds,
        translator=active_translator,
    )
    _score_open_events(repository, settings=settings, now=now)
    ranked = _eligible_events(repository, settings, now)
    day = production_date(now, settings.timezone)
    selections = repository.fill_daily_selections(
        client_id=settings.client_id,
        production_date=day,
        limit=settings.daily_reel_limit,
        candidates=[
            SelectionCandidate(event.event_id, event.score, event.story_class) for event in ranked
        ],
        now=now,
    )
    limitation = _LIMITATION if active_translator.name == "none" else None
    return IntakeReport(
        selections=tuple(selections),
        unfilled=max(settings.daily_reel_limit - len(selections), 0),
        failures=tuple(result.failures),
        articles_seen=len(articles),
        translation_provider=active_translator.name,
        limitation=limitation,
    )


def _configured_source(settings: Settings) -> object:
    sources = configured_news_sources(settings)
    if settings.news_provider == "rss" and not sources:
        raise ConfigurationError(
            "NEWS_PROVIDER=rss requires NEWS_SOURCES or NEWS_SOURCES_FILE. "
            "No default feeds are configured."
        )
    from app.services.factory import build_news_source

    return build_news_source(settings)


def _persist_articles(
    repository: NewsReelsRepository,
    *,
    settings: Settings,
    articles: list[DiscoveredArticle],
    now: datetime,
    stopwords: dict[str, frozenset[str]],
    aliases: dict[str, str],
    thresholds: MatchThresholds,
    translator: Translator,
) -> None:
    stored_events = repository.list_events(settings.client_id)
    stored_articles = repository.list_articles(settings.client_id)
    by_event: dict[str, list] = {}
    for stored in stored_articles:
        if stored.event_id:
            by_event.setdefault(stored.event_id, []).append(stored)
    known: list[WorkingCluster] = []
    for event in stored_events:
        texts = [
            ClusterText(
                title=article.title,
                summary=article.summary,
                language=(article.language or "und").lower(),
                canonical_url=article.canonical_url,
            )
            for article in by_event.get(event.id, [])
        ]
        if not texts:
            texts = [ClusterText(event.title, event.summary, "und")]
        known.append(WorkingCluster(key=event.id, state=event.state, persisted=True, texts=texts))
    incoming = [
        ClusterText(
            title=article.title,
            summary=article.summary,
            language=(article.language or "und").lower(),
            canonical_url=_safe_canonical(article.canonical_url),
        )
        for article in articles
    ]
    assignments = assign_articles(
        incoming,
        known,
        thresholds=thresholds,
        aliases=aliases,
        stopwords=stopwords,
        translator=translator,
    )
    event_ids: dict[str, str] = {}
    for assignment in assignments:
        article = articles[assignment.article_index]
        language = (article.language or "und").lower()
        stops = stopwords.get(language, frozenset())
        fingerprint = _fingerprint(article.title, stops, article.canonical_url)
        stored, _created = repository.upsert_article(
            ArticleInput(
                client_id=settings.client_id,
                source_name=article.source_name,
                source_url=article.source_url,
                canonical_url=article.canonical_url,
                title=article.title,
                normalized_title=normalize_headline(article.title) or article.title.lower(),
                title_fingerprint=fingerprint,
                summary=article.summary,
                published_at=utc_iso(article.published_at) if article.published_at else None,
                language=article.language,
                image_url=article.image_url,
                simhash=_optional_simhash(f"{article.title} {article.summary}", stops),
                entities=tuple(sorted(canonical_entities(f"{article.title} {article.summary}", aliases))),
                raw_payload=json.dumps({"source": article.source_name}, ensure_ascii=False),
            ),
            now=now,
        )
        event_id = event_ids.get(assignment.cluster_key)
        if event_id is None and not assignment.is_new:
            event_id = assignment.cluster_key
        if event_id is None:
            event_id = _open_event(
                repository,
                settings.client_id,
                article,
                fingerprint,
                stops,
                now,
            )
            event_ids[assignment.cluster_key] = event_id
        relation = "primary" if assignment.is_new else assignment.relation
        try:
            repository.attach_article_to_event(
                article_id=stored.id,
                event_id=event_id,
                relation=relation,
            )
        except ArticleAlreadyLinkedError:
            continue


def _open_event(
    repository: NewsReelsRepository,
    client_id: str,
    article: DiscoveredArticle,
    fingerprint: str,
    stopwords: frozenset[str],
    now: datetime,
) -> str:
    try:
        created = repository.insert_event(
            EventInput(
                client_id=client_id,
                event_fingerprint=fingerprint,
                block_key=block_key(article.title, stopwords),
                title=article.title,
                normalized_title=normalize_headline(article.title) or article.title.lower(),
                title_fingerprint=fingerprint,
                summary=article.summary,
                first_published_at=utc_iso(article.published_at) if article.published_at else None,
                source_urls=(_safe_canonical(article.canonical_url),),
            ),
            now=now,
        )
    except DuplicateEventError:
        existing = repository.get_event_by_fingerprint(client_id, fingerprint)
        if existing is None:
            raise
        return existing.id
    return created.id


def _score_open_events(
    repository: NewsReelsRepository,
    *,
    settings: Settings,
    now: datetime,
) -> None:
    articles = [article for article in repository.list_articles(settings.client_id) if article.event_id]
    grouped: dict[str, list] = {}
    for article in articles:
        grouped.setdefault(article.event_id, []).append(article)
    for event in repository.list_events(settings.client_id):
        if event.state != "DISCOVERED":
            continue
        linked = grouped.get(event.id, [])
        if not linked:
            continue
        latest = _latest_published(linked)
        band = recency_band(latest, now, settings.timezone)
        text = " ".join(f"{item.title} {item.summary}" for item in linked)
        opinion = any(is_opinion(item.canonical_url, item.title) for item in linked)
        sources = len({item.source_name for item in linked})
        scored = score_event(
            band=band,
            source_count=sources,
            impact=has_impact(text),
            opinion=opinion,
        )
        repository.update_event_assessment(
            event.id,
            importance_score=scored.score,
            story_class=scored.story_class,
            breakdown_json=json.dumps(
                {
                    "band": scored.band,
                    "source_count": scored.source_count,
                    "impact": scored.impact,
                }
            ),
            event_description=linked[0].summary,
        )


def _eligible_events(
    repository: NewsReelsRepository,
    settings: Settings,
    now: datetime,
) -> list[RankedEvent]:
    articles = [article for article in repository.list_articles(settings.client_id) if article.event_id]
    grouped: dict[str, list] = {}
    for article in articles:
        grouped.setdefault(article.event_id, []).append(article)
    ranked: list[RankedEvent] = []
    for event in repository.list_events(settings.client_id):
        if event.state != "DISCOVERED" or event.importance_score is None or event.story_class is None:
            continue
        linked = grouped.get(event.id, [])
        band = recency_band(_latest_published(linked), now, settings.timezone)
        source_count = len({item.source_name for item in linked})
        from app.services.news.scoring import EventScore

        scored = EventScore(event.importance_score, event.story_class, band, source_count, False)
        if not eligible(
            scored,
            minimum=settings.min_importance_score,
            older_minimum=settings.older_window_min_importance,
        ):
            continue
        ranked.append(
            RankedEvent(event.id, event.importance_score, event.story_class, band, source_count)
        )
    return order_events(ranked)


def _inside_window(article: DiscoveredArticle, start: datetime, end: datetime) -> bool:
    if article.published_at is None:
        return False
    moment = article.published_at.astimezone(timezone.utc)
    return start.astimezone(timezone.utc) <= moment <= end.astimezone(timezone.utc)


def _fingerprint(title: str, stopwords: frozenset[str], url: str) -> str:
    try:
        return title_fingerprint(title, stopwords)
    except ValueError:
        return hashlib.sha256(_safe_canonical(url).encode("utf-8")).hexdigest()


def _optional_simhash(text: str, stopwords: frozenset[str]) -> str | None:
    try:
        return simhash64(text, stopwords)
    except ValueError:
        return None


def _safe_canonical(url: str) -> str:
    try:
        return canonicalize_url(url)
    except ValueError:
        return url


def _latest_published(articles: list) -> datetime | None:
    moments = []
    for article in articles:
        if not article.published_at:
            continue
        parsed = datetime.fromisoformat(article.published_at)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        moments.append(parsed)
    if not moments:
        return None
    return max(moments)
