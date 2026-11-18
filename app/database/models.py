"""Row objects returned by the repository.

These are the persistence records. Agent boundaries use the Pydantic schemas.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Client:
    id: str
    name: str
    timezone: str
    daily_reel_limit: int
    created_at: str


@dataclass(frozen=True)
class ArticleInput:
    client_id: str
    source_name: str
    source_url: str
    canonical_url: str
    title: str
    normalized_title: str
    title_fingerprint: str
    summary: str = ""
    published_at: str | None = None
    language: str | None = None
    image_url: str | None = None
    simhash: str | None = None
    entities: tuple[str, ...] = ()
    raw_payload: str = "{}"


@dataclass(frozen=True)
class Article:
    id: str
    client_id: str
    source_name: str
    source_url: str
    canonical_url: str
    title: str
    normalized_title: str
    title_fingerprint: str
    summary: str
    published_at: str | None
    discovered_at: str
    language: str | None
    image_url: str | None
    simhash: str | None
    entities: tuple[str, ...]
    relation: str
    event_id: str | None
    raw_payload: str


@dataclass(frozen=True)
class EventInput:
    client_id: str
    event_fingerprint: str
    block_key: str
    title: str
    normalized_title: str
    title_fingerprint: str
    summary: str = ""
    entities: tuple[str, ...] = ()
    event_description: str = ""
    first_published_at: str | None = None
    source_urls: tuple[str, ...] = ()
    semantic_fingerprint: str | None = None
    story_class: str | None = None


@dataclass(frozen=True)
class Event:
    id: str
    client_id: str
    event_fingerprint: str
    block_key: str
    title: str
    normalized_title: str
    title_fingerprint: str
    summary: str
    entities: tuple[str, ...]
    event_description: str
    first_published_at: str | None
    last_published_at: str | None
    first_discovered_at: str
    source_urls: tuple[str, ...]
    article_count: int
    importance_score: float | None
    importance_breakdown: str | None
    story_class: str | None
    state: str
    semantic_fingerprint: str | None


@dataclass(frozen=True)
class GeneratedContent:
    id: str
    client_id: str
    event_id: str
    production_date: str
    slot_key: str
    state: str
    last_successful_state: str | None
    reserved_by: str | None
    script_json: str | None
    image_paths_json: str | None
    audio_path: str | None
    audio_duration_seconds: float | None
    video_path: str | None
    detail: str | None
    attempt_count: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class DailySlot:
    id: str
    client_id: str
    production_date: str
    slot_key: str
    status: str
    event_id: str | None
    content_id: str | None
    detail: str | None
    attempt_count: int
    started_at: str | None
    heartbeat_at: str | None
    finished_at: str | None


@dataclass(frozen=True)
class AgentLog:
    id: str
    client_id: str
    run_id: str
    agent_name: str
    status: str
    detail: str | None
    started_at: str
    finished_at: str | None
    duration_ms: int | None


@dataclass(frozen=True)
class NotificationRecord:
    id: str
    client_id: str
    provider: str
    status: str
    subject: str
    body: str
    content_id: str | None
    created_at: str
    sent_at: str | None
    detail: str | None


@dataclass(frozen=True)
class SelectionCandidate:
    """One eligible event, already ordered by the selector."""

    event_id: str
    importance_score: float
    story_class: str | None = None


@dataclass(frozen=True)
class EventSelection:
    """A permanent daily selection row. Rows are inserted and never rewritten."""

    id: str
    client_id: str
    event_id: str
    production_date: str
    rank: int
    importance_score: float
    story_class: str | None
    created_at: str


@dataclass(frozen=True)
class StatusSnapshot:
    schema_version: str | None
    client_count: int
    article_count: int
    event_count: int
    content_by_state: dict[str, int]
    completed_today: int
    slots_today: tuple[DailySlot, ...]
