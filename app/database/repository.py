"""SQLite repository.

The orchestrator is the only writer. Agents never open this database.
Quota, story reservation, and state changes that must survive a crash are
committed here in immediate transactions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from app.core.time import parse_utc, utc_iso
from app.database.connection import connect
from app.database.models import (
    AgentLog,
    Article,
    ArticleInput,
    Client,
    DailySlot,
    Event,
    EventInput,
    EventSelection,
    GeneratedContent,
    NotificationRecord,
    SelectionCandidate,
    StatusSnapshot,
)
from app.database.state import allowed_targets
from app.schemas.content import GenerationState
from app.services.dedup.url import canonicalize_url
from app.core.exceptions import (
    ArticleAlreadyLinkedError,
    DuplicateEventError,
    DuplicateStoryError,
    InvalidStateTransitionError,
    NotFoundError,
    PersistenceError,
    QuotaExceededError,
    SelectionConflict,
    SlotUnavailableError,
)

logger = logging.getLogger("news_reels.database")

_MIGRATIONS = Path(__file__).resolve().parent / "migrations"
_STORY_CLASSES = {"breaking", "major", "minor_update", "opinion", "duplicate"}
_RELATIONS = {"primary", "duplicate", "update"}
_TERMINAL = {GenerationState.COMPLETED.value, GenerationState.FAILED.value, GenerationState.SKIPPED.value}

_EVENT_COLUMNS = """
id, client_id, event_fingerprint, block_key, title, normalized_title, title_fingerprint,
summary, entities_json, event_description, first_published_at, last_published_at,
first_discovered_at, source_urls_json, article_count, importance_score,
importance_breakdown_json, story_class, state, semantic_fingerprint
"""

_ARTICLE_COLUMNS = """
id, client_id, source_name, source_url, canonical_url, title, normalized_title,
title_fingerprint, summary, published_at, discovered_at, language, image_url, simhash,
entities_json, relation, event_id, raw_payload
"""

_CONTENT_COLUMNS = """
id, client_id, event_id, production_date, slot_key, state, last_successful_state,
reserved_by, script_json, image_paths_json, audio_path, audio_duration_seconds,
video_path, detail, attempt_count, created_at, updated_at
"""

_SLOT_COLUMNS = """
id, client_id, production_date, slot_key, status, event_id, content_id, detail,
attempt_count, started_at, heartbeat_at, finished_at
"""


def _sql_statements(script: str) -> list[str]:
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


def _new_id() -> str:
    return str(uuid.uuid4())


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_list(value: str) -> tuple[str, ...]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise PersistenceError("expected a JSON list of strings")
    return tuple(parsed)


def _require_object_json(value: str, field: str) -> None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PersistenceError(f"{field} must be JSON") from exc
    if not isinstance(parsed, dict):
        raise PersistenceError(f"{field} must be a JSON object")


def _require_string_list_json(value: str, field: str) -> None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise PersistenceError(f"{field} must be JSON") from exc
    if not isinstance(parsed, list) or not parsed or any(not isinstance(item, str) or not item for item in parsed):
        raise PersistenceError(f"{field} must be a non-empty JSON list of paths")


def _stored_time(value: datetime | str | None, field: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return utc_iso(value)
    if isinstance(value, str) and value.strip():
        return utc_iso(parse_utc(value))
    raise ValueError(f"{field} must be a timezone-aware timestamp")


def _nonempty(value: str, field: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} is required")
    return cleaned


def _translate_integrity(exc: sqlite3.IntegrityError) -> PersistenceError:
    message = str(exc).lower()
    if "foreign key" in message:
        return PersistenceError("related row does not exist")
    if "news_events" in message:
        return DuplicateEventError("event fingerprint already exists")
    if "generated_content" in message:
        return DuplicateStoryError("event already has generated content")
    if "daily_production" in message:
        return SlotUnavailableError("production slot already exists")
    return PersistenceError(str(exc))


class NewsReelsRepository:
    """Transactional access to the reel database."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        return connect(self.path)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            connection.close()
            raise PersistenceError(f"could not start a transaction: {exc}") from exc
        try:
            yield connection
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.Error:
                logger.exception("rollback failed")
            raise
        else:
            connection.execute("COMMIT")
        finally:
            connection.close()

    def migrate(self) -> str:
        """Apply pending SQL migrations. Returns the latest version."""

        files = sorted(_MIGRATIONS.glob("*.sql"))
        if not files:
            raise PersistenceError("no database migrations are packaged")
        latest = ""
        with self._transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                row["version"]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for path in files:
                version = path.name.split("_", 1)[0]
                latest = version
                if version in applied:
                    continue
                for statement in _sql_statements(path.read_text(encoding="utf-8")):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, utc_iso(datetime.now().astimezone())),
                )
                logger.info("applied migration %s", version)
        return latest

    def initialize(
        self,
        *,
        client_id: str,
        name: str,
        timezone_name: str,
        daily_reel_limit: int,
        now: datetime,
    ) -> Client:
        """Create the schema and the default client. Safe to repeat."""

        self.migrate()
        return self.ensure_client(
            client_id=client_id,
            name=name,
            timezone_name=timezone_name,
            daily_reel_limit=daily_reel_limit,
            now=now,
        )

    def ensure_client(
        self,
        *,
        client_id: str,
        name: str,
        timezone_name: str,
        daily_reel_limit: int,
        now: datetime,
    ) -> Client:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO clients (id, name, timezone, daily_reel_limit, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    timezone = excluded.timezone,
                    daily_reel_limit = excluded.daily_reel_limit
                """,
                (client_id, name, timezone_name, daily_reel_limit, utc_iso(now)),
            )
            row = connection.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
        if row is None:
            raise PersistenceError("client row was not written")
        return _client(row)

    def upsert_article(self, article: ArticleInput, *, now: datetime) -> tuple[Article, bool]:
        """Insert an article or refresh an existing canonical URL. Returns created."""

        canonical = canonicalize_url(article.canonical_url)
        payload = article.raw_payload or "{}"
        _require_object_json(payload, "raw_payload")
        published = _stored_time(article.published_at, "published_at")
        entities = _json_dump(list(article.entities))
        discovered = utc_iso(now)
        values = {
            "client_id": _nonempty(article.client_id, "client_id"),
            "source_name": _nonempty(article.source_name, "source_name"),
            "source_url": _nonempty(article.source_url, "source_url"),
            "canonical_url": canonical,
            "title": _nonempty(article.title, "title"),
            "normalized_title": _nonempty(article.normalized_title, "normalized_title"),
            "title_fingerprint": _nonempty(article.title_fingerprint, "title_fingerprint"),
            "summary": article.summary,
            "published_at": published,
            "language": article.language,
            "image_url": article.image_url,
            "simhash": article.simhash,
            "entities_json": entities,
            "raw_payload": payload,
        }
        with self._transaction() as connection:
            existing = connection.execute(
                f"SELECT {_ARTICLE_COLUMNS} FROM news_articles WHERE client_id = ? AND canonical_url = ?",
                (values["client_id"], canonical),
            ).fetchone()
            if existing is None:
                article_id = _new_id()
                try:
                    connection.execute(
                        """
                        INSERT INTO news_articles (
                            id, client_id, source_name, source_url, canonical_url, title,
                            normalized_title, title_fingerprint, summary, published_at,
                            discovered_at, language, image_url, simhash, entities_json,
                            relation, event_id, raw_payload
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'primary', NULL, ?)
                        """,
                        (
                            article_id,
                            values["client_id"],
                            values["source_name"],
                            values["source_url"],
                            canonical,
                            values["title"],
                            values["normalized_title"],
                            values["title_fingerprint"],
                            values["summary"],
                            published,
                            discovered,
                            values["language"],
                            values["image_url"],
                            values["simhash"],
                            entities,
                            payload,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise _translate_integrity(exc) from exc
                stored = _require_article(connection, article_id)
                return stored, True
            connection.execute(
                """
                UPDATE news_articles SET
                    source_name = ?, source_url = ?, title = ?, normalized_title = ?,
                    title_fingerprint = ?, summary = ?, published_at = ?, language = ?,
                    image_url = ?, simhash = ?, entities_json = ?, raw_payload = ?
                WHERE id = ?
                """,
                (
                    values["source_name"],
                    values["source_url"],
                    values["title"],
                    values["normalized_title"],
                    values["title_fingerprint"],
                    values["summary"],
                    published,
                    values["language"],
                    values["image_url"],
                    values["simhash"],
                    entities,
                    payload,
                    existing["id"],
                ),
            )
            return _require_article(connection, existing["id"]), False

    def get_article_by_canonical_url(self, client_id: str, canonical_url: str) -> Article | None:
        key = canonicalize_url(canonical_url)
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT {_ARTICLE_COLUMNS} FROM news_articles WHERE client_id = ? AND canonical_url = ?",
                (client_id, key),
            ).fetchone()
        finally:
            connection.close()
        return _article(row) if row else None

    def insert_event(self, event: EventInput, *, now: datetime) -> Event:
        published = _stored_time(event.first_published_at, "first_published_at")
        if event.story_class is not None and event.story_class not in _STORY_CLASSES:
            raise ValueError(f"unknown story class: {event.story_class}")
        event_id = _new_id()
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO news_events (
                        id, client_id, event_fingerprint, block_key, title, normalized_title,
                        title_fingerprint, summary, entities_json, event_description,
                        first_published_at, last_published_at, first_discovered_at,
                        source_urls_json, article_count, importance_score,
                        importance_breakdown_json, story_class, state, semantic_fingerprint
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, NULL, ?, 'DISCOVERED', ?
                    )
                    """,
                    (
                        event_id,
                        _nonempty(event.client_id, "client_id"),
                        _nonempty(event.event_fingerprint, "event_fingerprint"),
                        _nonempty(event.block_key, "block_key"),
                        _nonempty(event.title, "title"),
                        _nonempty(event.normalized_title, "normalized_title"),
                        _nonempty(event.title_fingerprint, "title_fingerprint"),
                        event.summary,
                        _json_dump(list(event.entities)),
                        event.event_description,
                        published,
                        published,
                        utc_iso(now),
                        _json_dump(list(event.source_urls)),
                        event.story_class,
                        event.semantic_fingerprint,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise _translate_integrity(exc) from exc
            return _require_event(connection, event_id)

    def get_event(self, event_id: str) -> Event | None:
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT {_EVENT_COLUMNS} FROM news_events WHERE id = ?",
                (event_id,),
            ).fetchone()
        finally:
            connection.close()
        return _event(row) if row else None

    def get_event_by_fingerprint(self, client_id: str, event_fingerprint: str) -> Event | None:
        connection = self._connect()
        try:
            row = connection.execute(
                f"""
                SELECT {_EVENT_COLUMNS} FROM news_events
                WHERE client_id = ? AND event_fingerprint = ?
                """,
                (client_id, event_fingerprint),
            ).fetchone()
        finally:
            connection.close()
        return _event(row) if row else None

    def list_events_by_title_fingerprint(self, client_id: str, title_fingerprint: str) -> list[Event]:
        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT {_EVENT_COLUMNS} FROM news_events
                WHERE client_id = ? AND title_fingerprint = ?
                ORDER BY first_discovered_at
                """,
                (client_id, title_fingerprint),
            ).fetchall()
        finally:
            connection.close()
        return [_event(row) for row in rows]

    def list_events(self, client_id: str) -> list[Event]:
        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT {_EVENT_COLUMNS} FROM news_events
                WHERE client_id = ?
                ORDER BY first_discovered_at
                """,
                (client_id,),
            ).fetchall()
        finally:
            connection.close()
        return [_event(row) for row in rows]

    def list_articles(self, client_id: str) -> list[Article]:
        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT {_ARTICLE_COLUMNS} FROM news_articles
                WHERE client_id = ?
                ORDER BY discovered_at
                """,
                (client_id,),
            ).fetchall()
        finally:
            connection.close()
        return [_article(row) for row in rows]

    def list_daily_selections(self, client_id: str, production_date: str) -> list[EventSelection]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT id, client_id, event_id, production_date, rank,
                       importance_score, story_class, created_at
                FROM event_selections
                WHERE client_id = ? AND production_date = ?
                ORDER BY rank
                """,
                (client_id, production_date),
            ).fetchall()
        finally:
            connection.close()
        return [_selection(row) for row in rows]

    def fill_daily_selections(
        self,
        *,
        client_id: str,
        production_date: str,
        limit: int,
        candidates: list[SelectionCandidate] | tuple[SelectionCandidate, ...],
        now: datetime,
        attempts: int = 8,
    ) -> list[EventSelection]:
        """Insert only the missing ranks for this local date.

        Stored rows stay as they are. The same event cannot be selected again
        on a later date. A conflicting concurrent insert rolls back and retries.
        """

        if not 0 <= limit <= 24:
            raise ValueError("daily selection limit must be from 0 to 24")
        if limit == 0:
            return self.list_daily_selections(client_id, production_date)
        last_conflict: Exception | None = None
        for _ in range(attempts):
            try:
                return self._fill_daily_selections_once(
                    client_id=client_id,
                    production_date=production_date,
                    limit=limit,
                    candidates=candidates,
                    now=now,
                )
            except SelectionConflict as exc:
                last_conflict = exc
            except PersistenceError as exc:
                if "could not start a transaction" not in str(exc):
                    raise
                last_conflict = exc
        raise PersistenceError("concurrent selection fill did not settle") from last_conflict

    def _fill_daily_selections_once(
        self,
        *,
        client_id: str,
        production_date: str,
        limit: int,
        candidates: list[SelectionCandidate] | tuple[SelectionCandidate, ...],
        now: datetime,
    ) -> list[EventSelection]:
        with self._transaction() as connection:
            existing = _selection_rows(connection, client_id, production_date)
            if len(existing) >= limit:
                return existing
            taken = {
                row["event_id"]
                for row in connection.execute(
                    "SELECT event_id FROM event_selections WHERE client_id = ?",
                    (client_id,),
                )
            }
            used_ranks = {row.rank for row in existing}
            for candidate in candidates:
                if len(existing) >= limit:
                    break
                if candidate.event_id in taken:
                    continue
                if not 0 <= candidate.importance_score <= 1:
                    raise ValueError("importance_score must be between 0 and 1")
                event = connection.execute(
                    f"SELECT {_EVENT_COLUMNS} FROM news_events WHERE id = ?",
                    (candidate.event_id,),
                ).fetchone()
                if event is None or event["client_id"] != client_id:
                    continue
                if event["state"] != GenerationState.DISCOVERED.value:
                    continue
                content = connection.execute(
                    """
                    SELECT 1 AS present FROM generated_content
                    WHERE client_id = ? AND event_id = ?
                    """,
                    (client_id, candidate.event_id),
                ).fetchone()
                if content is not None:
                    continue
                rank = 1
                while rank in used_ranks:
                    rank += 1
                if rank > limit or rank > 24:
                    break
                selection_id = _new_id()
                try:
                    connection.execute(
                        """
                        INSERT INTO event_selections (
                            id, client_id, event_id, production_date, rank,
                            importance_score, story_class, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            selection_id,
                            client_id,
                            candidate.event_id,
                            production_date,
                            rank,
                            candidate.importance_score,
                            candidate.story_class,
                            utc_iso(now),
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise SelectionConflict("selection row already exists") from exc
                taken.add(candidate.event_id)
                used_ranks.add(rank)
                existing.append(
                    EventSelection(
                        id=selection_id,
                        client_id=client_id,
                        event_id=candidate.event_id,
                        production_date=production_date,
                        rank=rank,
                        importance_score=candidate.importance_score,
                        story_class=candidate.story_class,
                        created_at=utc_iso(now),
                    )
                )
            return existing

    def update_event_assessment(
        self,
        event_id: str,
        *,
        importance_score: float | None,
        story_class: str | None,
        breakdown_json: str | None,
        event_description: str | None = None,
    ) -> Event:
        """Score an event that is still open. Completed history is not rewritten."""

        if importance_score is not None and not 0 <= importance_score <= 1:
            raise ValueError("importance_score must be between 0 and 1")
        if story_class is not None and story_class not in _STORY_CLASSES:
            raise ValueError(f"unknown story class: {story_class}")
        if breakdown_json is not None:
            _require_object_json(breakdown_json, "importance_breakdown")
        with self._transaction() as connection:
            current = _require_event(connection, event_id)
            if current.state != GenerationState.DISCOVERED.value:
                raise InvalidStateTransitionError("assessment is frozen after selection")
            connection.execute(
                """
                UPDATE news_events SET
                    importance_score = ?,
                    story_class = ?,
                    importance_breakdown_json = ?,
                    event_description = COALESCE(?, event_description)
                WHERE id = ?
                """,
                (importance_score, story_class, breakdown_json, event_description, event_id),
            )
            return _require_event(connection, event_id)

    def attach_article_to_event(
        self,
        *,
        article_id: str,
        event_id: str,
        relation: str,
    ) -> Event:
        """Link an article to an event. Repeating the same link is a no-op."""

        if relation not in _RELATIONS:
            raise ValueError(f"unknown article relation: {relation}")
        with self._transaction() as connection:
            article = _require_article(connection, article_id)
            event = _require_event(connection, event_id)
            if article.client_id != event.client_id:
                raise PersistenceError("article and event belong to different clients")
            if article.event_id is not None and article.event_id != event_id:
                raise ArticleAlreadyLinkedError("article is already linked to another event")
            first_link = article.event_id is None
            connection.execute(
                "UPDATE news_articles SET event_id = ?, relation = ? WHERE id = ?",
                (event_id, relation, article_id),
            )
            urls = list(event.source_urls)
            if article.canonical_url not in urls:
                urls.append(article.canonical_url)
            connection.execute(
                """
                UPDATE news_events SET
                    source_urls_json = ?,
                    article_count = ?,
                    first_published_at = ?,
                    last_published_at = ?
                WHERE id = ?
                """,
                (
                    _json_dump(urls),
                    event.article_count + (1 if first_link else 0),
                    _earlier(event.first_published_at, article.published_at),
                    _later(event.last_published_at, article.published_at),
                    event_id,
                ),
            )
            return _require_event(connection, event_id)

    def reserve_daily_slot(
        self,
        *,
        client_id: str,
        production_date: str,
        slot_key: str,
        daily_limit: int,
        now: datetime,
        stale_after: timedelta,
    ) -> DailySlot:
        """Reserve one slot if the client is still under the daily reel limit.

        A fresh running slot is left alone. A stale running slot is failed and,
        when it is the requested slot, immediately reopened for retry.
        """

        if daily_limit < 0:
            raise ValueError("daily_limit cannot be negative")
        if stale_after.total_seconds() <= 0:
            raise ValueError("stale_after must be positive")
        with self._transaction() as connection:
            self._expire_foreign_slots(
                connection,
                client_id=client_id,
                production_date=production_date,
                slot_key=slot_key,
                now=now,
                stale_after=stale_after,
            )
            current = _find_slot(connection, client_id, production_date, slot_key)
            if current is not None and current.status == "RUNNING" and _is_stale(current, now, stale_after):
                self._expire_slot(connection, current, now)
                current = _find_slot(connection, client_id, production_date, slot_key)
            completed = _completed_count(connection, client_id, production_date)
            if current is None:
                if completed >= daily_limit:
                    raise QuotaExceededError("daily reel limit has been reached")
                return _insert_slot(connection, client_id, production_date, slot_key, now)
            if current.status in {"COMPLETED", "SKIPPED"}:
                raise SlotUnavailableError(f"slot {slot_key} is already {current.status.lower()}")
            if current.status == "RUNNING":
                raise SlotUnavailableError(f"slot {slot_key} is already running")
            if completed >= daily_limit:
                raise QuotaExceededError("daily reel limit has been reached")
            reopened = connection.execute(
                """
                UPDATE daily_production SET
                    status = 'RUNNING',
                    detail = NULL,
                    attempt_count = ?,
                    started_at = ?,
                    heartbeat_at = ?,
                    finished_at = NULL
                WHERE id = ? AND status = 'FAILED'
                """,
                (current.attempt_count + 1, utc_iso(now), utc_iso(now), current.id),
            )
            if reopened.rowcount != 1:
                raise SlotUnavailableError(f"slot {slot_key} could not be reserved")
            slot = _require_slot(connection, current.id)
            return slot

    def heartbeat_slot(self, slot_id: str, now: datetime) -> DailySlot:
        with self._transaction() as connection:
            slot = _require_slot(connection, slot_id)
            if slot.status != "RUNNING":
                raise InvalidStateTransitionError("only a running slot accepts a heartbeat")
            connection.execute(
                "UPDATE daily_production SET heartbeat_at = ? WHERE id = ?",
                (utc_iso(now), slot_id),
            )
            return _require_slot(connection, slot_id)

    def skip_unbound_slot(self, slot_id: str, detail: str, now: datetime) -> DailySlot:
        """Close a slot that has no story, usually because no qualifying news exists."""

        return self._close_unbound_slot(slot_id, "SKIPPED", detail, now)

    def fail_unbound_slot(self, slot_id: str, detail: str, now: datetime) -> DailySlot:
        """Record a slot failure that happened before a story was reserved."""

        return self._close_unbound_slot(slot_id, "FAILED", detail, now)

    def reserve_event_for_generation(
        self,
        *,
        client_id: str,
        event_id: str,
        production_date: str,
        slot_key: str,
        owner: str,
        now: datetime,
    ) -> GeneratedContent:
        """Bind one open event to a running slot.

        A second run cannot create another reel for the same event. A failed
        reel can be resumed by a new owner on the same slot.
        """

        owner_id = _nonempty(owner, "owner")
        with self._transaction() as connection:
            slot = _find_slot(connection, client_id, production_date, slot_key)
            if slot is None:
                raise NotFoundError("production slot is not reserved")
            if slot.status != "RUNNING":
                raise SlotUnavailableError("production slot is not running")
            event = _require_event(connection, event_id)
            if event.client_id != client_id:
                raise PersistenceError("event belongs to a different client")
            if slot.event_id not in (None, event_id):
                raise PersistenceError("slot is bound to a different event")
            existing = connection.execute(
                f"SELECT {_CONTENT_COLUMNS} FROM generated_content WHERE client_id = ? AND event_id = ?",
                (client_id, event_id),
            ).fetchone()
            if existing is None:
                if event.state != GenerationState.DISCOVERED.value:
                    raise DuplicateStoryError("event is not open for a new reel")
                content_id = _new_id()
                stamp = utc_iso(now)
                try:
                    connection.execute(
                        """
                        INSERT INTO generated_content (
                            id, client_id, event_id, production_date, slot_key, state,
                            last_successful_state, reserved_by, detail, attempt_count,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, 'SELECTED', 'SELECTED', ?, NULL, 1, ?, ?)
                        """,
                        (content_id, client_id, event_id, production_date, slot_key, owner_id, stamp, stamp),
                    )
                except sqlite3.IntegrityError as exc:
                    raise _translate_integrity(exc) from exc
                claimed = connection.execute(
                    """
                    UPDATE news_events SET state = 'SELECTED'
                    WHERE id = ? AND state = 'DISCOVERED'
                    """,
                    (event_id,),
                )
                if claimed.rowcount != 1:
                    raise DuplicateStoryError("event was claimed by another run")
                self._bind_slot(connection, slot.id, event_id, content_id)
                return _require_content(connection, content_id)

            content = _content(existing)
            if content.production_date != production_date or content.slot_key != slot_key:
                raise DuplicateStoryError("event is bound to another production slot")
            if content.state in {GenerationState.COMPLETED.value, GenerationState.SKIPPED.value}:
                raise DuplicateStoryError("event already has a finished reel")
            if content.state != GenerationState.FAILED.value and content.reserved_by not in (None, owner_id):
                raise DuplicateStoryError("event is reserved by another run")
            if content.state == GenerationState.FAILED.value:
                connection.execute(
                    """
                    UPDATE generated_content
                    SET reserved_by = ?, attempt_count = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (owner_id, content.attempt_count + 1, utc_iso(now), content.id),
                )
            elif content.reserved_by is None:
                connection.execute(
                    "UPDATE generated_content SET reserved_by = ?, updated_at = ? WHERE id = ?",
                    (owner_id, utc_iso(now), content.id),
                )
            self._bind_slot(connection, slot.id, event_id, content.id)
            return _require_content(connection, content.id)

    def transition_generation_state(
        self,
        content_id: str,
        new_state: GenerationState | str,
        now: datetime,
        *,
        detail: str | None = None,
        script_json: str | None = None,
        image_paths_json: str | None = None,
        audio_path: str | None = None,
        audio_duration_seconds: float | None = None,
        video_path: str | None = None,
    ) -> GeneratedContent:
        """Move a reel one legal step and store the artifact for that step."""

        with self._transaction() as connection:
            content = _require_content(connection, content_id)
            return self._apply_transition(
                connection,
                content,
                GenerationState(new_state),
                now,
                detail=detail,
                script_json=script_json,
                image_paths_json=image_paths_json,
                audio_path=audio_path,
                audio_duration_seconds=audio_duration_seconds,
                video_path=video_path,
            )

    def get_content(self, content_id: str) -> GeneratedContent | None:
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT {_CONTENT_COLUMNS} FROM generated_content WHERE id = ?",
                (content_id,),
            ).fetchone()
        finally:
            connection.close()
        return _content(row) if row else None

    def get_content_for_event(self, client_id: str, event_id: str) -> GeneratedContent | None:
        connection = self._connect()
        try:
            row = connection.execute(
                f"SELECT {_CONTENT_COLUMNS} FROM generated_content WHERE client_id = ? AND event_id = ?",
                (client_id, event_id),
            ).fetchone()
        finally:
            connection.close()
        return _content(row) if row else None

    def count_completed_reels(self, client_id: str, production_date: str) -> int:
        connection = self._connect()
        try:
            return _completed_count(connection, client_id, production_date)
        finally:
            connection.close()

    def list_daily_production(self, client_id: str, production_date: str) -> list[DailySlot]:
        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT {_SLOT_COLUMNS} FROM daily_production
                WHERE client_id = ? AND production_date = ?
                ORDER BY slot_key
                """,
                (client_id, production_date),
            ).fetchall()
        finally:
            connection.close()
        return [_slot(row) for row in rows]

    def acquire_job_lock(self, lock_name: str, owner: str, now: datetime, ttl: timedelta) -> bool:
        """Take a named lock. An expired lock can be taken by a new owner."""

        if ttl.total_seconds() <= 0:
            raise ValueError("ttl must be positive")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT owner, expires_at FROM job_locks WHERE lock_name = ?",
                (lock_name,),
            ).fetchone()
            if row is not None:
                if parse_utc(row["expires_at"]) > utc_now(now) and row["owner"] != owner:
                    return False
                connection.execute("DELETE FROM job_locks WHERE lock_name = ?", (lock_name,))
            connection.execute(
                """
                INSERT INTO job_locks (lock_name, owner, acquired_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (lock_name, _nonempty(owner, "owner"), utc_iso(now), utc_iso(utc_now(now) + ttl)),
            )
            return True

    def refresh_job_lock(self, lock_name: str, owner: str, now: datetime, ttl: timedelta) -> bool:
        if ttl.total_seconds() <= 0:
            raise ValueError("ttl must be positive")
        with self._transaction() as connection:
            updated = connection.execute(
                "UPDATE job_locks SET expires_at = ? WHERE lock_name = ? AND owner = ?",
                (utc_iso(utc_now(now) + ttl), lock_name, owner),
            )
            return updated.rowcount == 1

    def release_job_lock(self, lock_name: str, owner: str) -> bool:
        with self._transaction() as connection:
            released = connection.execute(
                "DELETE FROM job_locks WHERE lock_name = ? AND owner = ?",
                (lock_name, owner),
            )
            return released.rowcount == 1

    def start_agent_run(
        self,
        *,
        client_id: str,
        run_id: str,
        agent_name: str,
        now: datetime,
    ) -> AgentLog:
        log_id = _new_id()
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO agent_execution_logs (
                        id, client_id, run_id, agent_name, status, started_at
                    ) VALUES (?, ?, ?, ?, 'STARTED', ?)
                    """,
                    (log_id, client_id, _nonempty(run_id, "run_id"), _nonempty(agent_name, "agent_name"), utc_iso(now)),
                )
            except sqlite3.IntegrityError as exc:
                raise _translate_integrity(exc) from exc
            return _require_log(connection, log_id)

    def finish_agent_run(
        self,
        log_id: str,
        *,
        status: str,
        now: datetime,
        detail: str | None = None,
    ) -> AgentLog:
        if status not in {"SUCCEEDED", "FAILED"}:
            raise ValueError("agent run must finish as SUCCEEDED or FAILED")
        with self._transaction() as connection:
            current = _require_log(connection, log_id)
            if current.status != "STARTED":
                raise InvalidStateTransitionError("agent run has already finished")
            started = parse_utc(current.started_at)
            duration_ms = max(0, int((utc_now(now) - started).total_seconds() * 1000))
            connection.execute(
                """
                UPDATE agent_execution_logs
                SET status = ?, detail = ?, finished_at = ?, duration_ms = ?
                WHERE id = ?
                """,
                (status, detail, utc_iso(now), duration_ms, log_id),
            )
            return _require_log(connection, log_id)

    def record_notification(
        self,
        *,
        client_id: str,
        provider: str,
        status: str,
        subject: str,
        body: str,
        now: datetime,
        content_id: str | None = None,
        detail: str | None = None,
    ) -> NotificationRecord:
        if status not in {"PENDING", "SENT", "FAILED"}:
            raise ValueError("notification status must be PENDING, SENT, or FAILED")
        note_id = _new_id()
        sent_at = utc_iso(now) if status == "SENT" else None
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO notifications (
                        id, client_id, provider, status, subject, body, content_id,
                        created_at, sent_at, detail
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note_id,
                        client_id,
                        _nonempty(provider, "provider"),
                        status,
                        _nonempty(subject, "subject"),
                        _nonempty(body, "body"),
                        content_id,
                        utc_iso(now),
                        sent_at,
                        detail,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise _translate_integrity(exc) from exc
            row = connection.execute("SELECT * FROM notifications WHERE id = ?", (note_id,)).fetchone()
        if row is None:
            raise PersistenceError("notification was not written")
        return _notification(row)

    def set_config(self, client_id: str, key: str, value: object, now: datetime) -> None:
        encoded = _json_dump(value)
        with self._transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO app_config (client_id, key, value_json, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(client_id, key) DO UPDATE SET
                        value_json = excluded.value_json,
                        updated_at = excluded.updated_at
                    """,
                    (client_id, _nonempty(key, "key"), encoded, utc_iso(now)),
                )
            except sqlite3.IntegrityError as exc:
                raise _translate_integrity(exc) from exc

    def get_config(self, client_id: str, key: str) -> object | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT value_json FROM app_config WHERE client_id = ? AND key = ?",
                (client_id, key),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return json.loads(row["value_json"])

    def status_snapshot(self, client_id: str, production_date: str) -> StatusSnapshot:
        connection = self._connect()
        try:
            version_row = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
            content_rows = connection.execute(
                """
                SELECT state, COUNT(*) AS total
                FROM generated_content
                WHERE client_id = ?
                GROUP BY state
                """,
                (client_id,),
            ).fetchall()
            slots = connection.execute(
                f"""
                SELECT {_SLOT_COLUMNS} FROM daily_production
                WHERE client_id = ? AND production_date = ?
                ORDER BY slot_key
                """,
                (client_id, production_date),
            ).fetchall()
            snapshot = StatusSnapshot(
                schema_version=version_row["version"] if version_row else None,
                client_count=int(connection.execute("SELECT COUNT(*) AS c FROM clients").fetchone()["c"]),
                article_count=int(
                    connection.execute(
                        "SELECT COUNT(*) AS c FROM news_articles WHERE client_id = ?",
                        (client_id,),
                    ).fetchone()["c"]
                ),
                event_count=int(
                    connection.execute(
                        "SELECT COUNT(*) AS c FROM news_events WHERE client_id = ?",
                        (client_id,),
                    ).fetchone()["c"]
                ),
                content_by_state={row["state"]: int(row["total"]) for row in content_rows},
                completed_today=_completed_count(connection, client_id, production_date),
                slots_today=tuple(_slot(row) for row in slots),
            )
        finally:
            connection.close()
        return snapshot

    def _close_unbound_slot(self, slot_id: str, status: str, detail: str, now: datetime) -> DailySlot:
        reason = _nonempty(detail, "detail")
        with self._transaction() as connection:
            slot = _require_slot(connection, slot_id)
            if slot.status != "RUNNING":
                raise InvalidStateTransitionError("only a running slot can be closed")
            if slot.event_id is not None or slot.content_id is not None:
                raise PersistenceError("a bound slot is closed through the generation state")
            connection.execute(
                """
                UPDATE daily_production
                SET status = ?, detail = ?, finished_at = ?
                WHERE id = ?
                """,
                (status, reason, utc_iso(now), slot_id),
            )
            return _require_slot(connection, slot_id)

    def _expire_foreign_slots(
        self,
        connection: sqlite3.Connection,
        *,
        client_id: str,
        production_date: str,
        slot_key: str,
        now: datetime,
        stale_after: timedelta,
    ) -> None:
        rows = connection.execute(
            f"SELECT {_SLOT_COLUMNS} FROM daily_production WHERE client_id = ? AND status = 'RUNNING'",
            (client_id,),
        ).fetchall()
        for row in rows:
            slot = _slot(row)
            if slot.production_date == production_date and slot.slot_key == slot_key:
                continue
            if _is_stale(slot, now, stale_after):
                self._expire_slot(connection, slot, now)
                continue
            raise SlotUnavailableError(
                f"slot {slot.production_date} {slot.slot_key} is already running"
            )

    def _expire_slot(self, connection: sqlite3.Connection, slot: DailySlot, now: datetime) -> None:
        if slot.content_id:
            content = _content_or_none(connection, slot.content_id)
            if content is not None and content.state not in _TERMINAL:
                self._apply_transition(
                    connection,
                    content,
                    GenerationState.FAILED,
                    now,
                    detail="slot heartbeat expired",
                )
                return
        connection.execute(
            """
            UPDATE daily_production
            SET status = 'FAILED', detail = ?, finished_at = ?
            WHERE id = ? AND status = 'RUNNING'
            """,
            ("slot heartbeat expired", utc_iso(now), slot.id),
        )

    def _bind_slot(self, connection: sqlite3.Connection, slot_id: str, event_id: str, content_id: str) -> None:
        updated = connection.execute(
            """
            UPDATE daily_production
            SET event_id = ?, content_id = ?
            WHERE id = ? AND status = 'RUNNING'
            """,
            (event_id, content_id, slot_id),
        )
        if updated.rowcount != 1:
            raise SlotUnavailableError("production slot is not running")

    def _apply_transition(
        self,
        connection: sqlite3.Connection,
        content: GeneratedContent,
        target: GenerationState,
        now: datetime,
        *,
        detail: str | None = None,
        script_json: str | None = None,
        image_paths_json: str | None = None,
        audio_path: str | None = None,
        audio_duration_seconds: float | None = None,
        video_path: str | None = None,
    ) -> GeneratedContent:
        current = GenerationState(content.state)
        last = GenerationState(content.last_successful_state) if content.last_successful_state else None
        if target not in allowed_targets(current, last):
            raise InvalidStateTransitionError(f"cannot move from {current.value} to {target.value}")
        slot = _find_slot(connection, content.client_id, content.production_date, content.slot_key)
        if slot is None or slot.status != "RUNNING":
            raise SlotUnavailableError("production slot is not running")
        if slot.event_id not in (None, content.event_id):
            raise PersistenceError("slot is bound to a different event")

        script = content.script_json if script_json is None else script_json
        images = content.image_paths_json if image_paths_json is None else image_paths_json
        audio = content.audio_path if audio_path is None else audio_path
        duration = content.audio_duration_seconds if audio_duration_seconds is None else audio_duration_seconds
        video = content.video_path if video_path is None else video_path
        if script_json is not None:
            _require_object_json(script_json, "script_json")
        if image_paths_json is not None:
            _require_string_list_json(image_paths_json, "image_paths_json")
        if duration is not None and duration <= 0:
            raise PersistenceError("audio duration must be positive")
        if target is GenerationState.SCRIPT_GENERATED and not script:
            raise PersistenceError("SCRIPT_GENERATED requires script_json")
        if target is GenerationState.IMAGES_GENERATED and not images:
            raise PersistenceError("IMAGES_GENERATED requires image_paths_json")
        if target is GenerationState.AUDIO_GENERATED and (not audio or not duration):
            raise PersistenceError("AUDIO_GENERATED requires audio_path and duration")
        if target in {GenerationState.VIDEO_RENDERED, GenerationState.COMPLETED} and not video:
            raise PersistenceError(f"{target.value} requires video_path")
        if target in {GenerationState.FAILED, GenerationState.SKIPPED} and not (detail and detail.strip()):
            raise PersistenceError(f"{target.value} requires a detail message")

        if target in {GenerationState.FAILED, GenerationState.SKIPPED}:
            stored_detail: str | None = detail.strip() if detail else None
            stored_last = content.last_successful_state
        elif target is GenerationState.COMPLETED:
            stored_detail = None
            stored_last = target.value
        else:
            stored_detail = content.detail if detail is None else detail
            stored_last = target.value

        stamp = utc_iso(now)
        connection.execute(
            """
            UPDATE generated_content SET
                state = ?, last_successful_state = ?, script_json = ?, image_paths_json = ?,
                audio_path = ?, audio_duration_seconds = ?, video_path = ?, detail = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (target.value, stored_last, script, images, audio, duration, video, stored_detail, stamp, content.id),
        )
        connection.execute(
            "UPDATE news_events SET state = ? WHERE id = ?",
            (target.value, content.event_id),
        )
        if slot.content_id != content.id or slot.event_id != content.event_id:
            self._bind_slot(connection, slot.id, content.event_id, content.id)
        if target in {GenerationState.COMPLETED, GenerationState.FAILED, GenerationState.SKIPPED}:
            slot_status = {
                GenerationState.COMPLETED: "COMPLETED",
                GenerationState.FAILED: "FAILED",
                GenerationState.SKIPPED: "SKIPPED",
            }[target]
            updated = connection.execute(
                """
                UPDATE daily_production
                SET status = ?, detail = ?, finished_at = ?, content_id = ?, event_id = ?
                WHERE id = ? AND status = 'RUNNING'
                """,
                (slot_status, stored_detail, stamp, content.id, content.event_id, slot.id),
            )
            if updated.rowcount != 1:
                raise PersistenceError("production slot could not be closed")
        return _require_content(connection, content.id)


def utc_now(value: datetime) -> datetime:
    return parse_utc(utc_iso(value))


def _earlier(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if parse_utc(left) <= parse_utc(right) else right


def _later(left: str | None, right: str | None) -> str | None:
    if left is None:
        return right
    if right is None:
        return left
    return left if parse_utc(left) >= parse_utc(right) else right


def _is_stale(slot: DailySlot, now: datetime, stale_after: timedelta) -> bool:
    stamp = slot.heartbeat_at or slot.started_at
    if stamp is None:
        return True
    return parse_utc(stamp) <= utc_now(now) - stale_after


def _completed_count(connection: sqlite3.Connection, client_id: str, production_date: str) -> int:
    row = connection.execute(
        """
        SELECT COUNT(*) AS total FROM daily_production
        WHERE client_id = ? AND production_date = ? AND status = 'COMPLETED'
        """,
        (client_id, production_date),
    ).fetchone()
    return int(row["total"])


def _insert_slot(
    connection: sqlite3.Connection,
    client_id: str,
    production_date: str,
    slot_key: str,
    now: datetime,
) -> DailySlot:
    slot_id = _new_id()
    stamp = utc_iso(now)
    try:
        connection.execute(
            """
            INSERT INTO daily_production (
                id, client_id, production_date, slot_key, status, attempt_count,
                started_at, heartbeat_at
            ) VALUES (?, ?, ?, ?, 'RUNNING', 1, ?, ?)
            """,
            (slot_id, client_id, production_date, slot_key, stamp, stamp),
        )
    except sqlite3.IntegrityError as exc:
        raise _translate_integrity(exc) from exc
    return _require_slot(connection, slot_id)


def _find_slot(
    connection: sqlite3.Connection,
    client_id: str,
    production_date: str,
    slot_key: str,
) -> DailySlot | None:
    row = connection.execute(
        f"""
        SELECT {_SLOT_COLUMNS} FROM daily_production
        WHERE client_id = ? AND production_date = ? AND slot_key = ?
        """,
        (client_id, production_date, slot_key),
    ).fetchone()
    return _slot(row) if row else None


def _content_or_none(connection: sqlite3.Connection, content_id: str) -> GeneratedContent | None:
    row = connection.execute(
        f"SELECT {_CONTENT_COLUMNS} FROM generated_content WHERE id = ?",
        (content_id,),
    ).fetchone()
    return _content(row) if row else None


def _require_article(connection: sqlite3.Connection, article_id: str) -> Article:
    row = connection.execute(
        f"SELECT {_ARTICLE_COLUMNS} FROM news_articles WHERE id = ?",
        (article_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"article {article_id} does not exist")
    return _article(row)


def _require_event(connection: sqlite3.Connection, event_id: str) -> Event:
    row = connection.execute(
        f"SELECT {_EVENT_COLUMNS} FROM news_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"event {event_id} does not exist")
    return _event(row)


def _require_content(connection: sqlite3.Connection, content_id: str) -> GeneratedContent:
    loaded = _content_or_none(connection, content_id)
    if loaded is None:
        raise NotFoundError(f"content {content_id} does not exist")
    return loaded


def _require_slot(connection: sqlite3.Connection, slot_id: str) -> DailySlot:
    row = connection.execute(
        f"SELECT {_SLOT_COLUMNS} FROM daily_production WHERE id = ?",
        (slot_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"slot {slot_id} does not exist")
    return _slot(row)


def _require_log(connection: sqlite3.Connection, log_id: str) -> AgentLog:
    row = connection.execute("SELECT * FROM agent_execution_logs WHERE id = ?", (log_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"agent log {log_id} does not exist")
    return _log(row)


def _client(row: sqlite3.Row) -> Client:
    return Client(
        id=row["id"],
        name=row["name"],
        timezone=row["timezone"],
        daily_reel_limit=int(row["daily_reel_limit"]),
        created_at=row["created_at"],
    )


def _article(row: sqlite3.Row) -> Article:
    return Article(
        id=row["id"],
        client_id=row["client_id"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        canonical_url=row["canonical_url"],
        title=row["title"],
        normalized_title=row["normalized_title"],
        title_fingerprint=row["title_fingerprint"],
        summary=row["summary"],
        published_at=row["published_at"],
        discovered_at=row["discovered_at"],
        language=row["language"],
        image_url=row["image_url"],
        simhash=row["simhash"],
        entities=_json_list(row["entities_json"]),
        relation=row["relation"],
        event_id=row["event_id"],
        raw_payload=row["raw_payload"],
    )


def _event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        client_id=row["client_id"],
        event_fingerprint=row["event_fingerprint"],
        block_key=row["block_key"],
        title=row["title"],
        normalized_title=row["normalized_title"],
        title_fingerprint=row["title_fingerprint"],
        summary=row["summary"],
        entities=_json_list(row["entities_json"]),
        event_description=row["event_description"],
        first_published_at=row["first_published_at"],
        last_published_at=row["last_published_at"],
        first_discovered_at=row["first_discovered_at"],
        source_urls=_json_list(row["source_urls_json"]),
        article_count=int(row["article_count"]),
        importance_score=row["importance_score"],
        importance_breakdown=row["importance_breakdown_json"],
        story_class=row["story_class"],
        state=row["state"],
        semantic_fingerprint=row["semantic_fingerprint"],
    )


def _content(row: sqlite3.Row) -> GeneratedContent:
    return GeneratedContent(
        id=row["id"],
        client_id=row["client_id"],
        event_id=row["event_id"],
        production_date=row["production_date"],
        slot_key=row["slot_key"],
        state=row["state"],
        last_successful_state=row["last_successful_state"],
        reserved_by=row["reserved_by"],
        script_json=row["script_json"],
        image_paths_json=row["image_paths_json"],
        audio_path=row["audio_path"],
        audio_duration_seconds=row["audio_duration_seconds"],
        video_path=row["video_path"],
        detail=row["detail"],
        attempt_count=int(row["attempt_count"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _slot(row: sqlite3.Row) -> DailySlot:
    return DailySlot(
        id=row["id"],
        client_id=row["client_id"],
        production_date=row["production_date"],
        slot_key=row["slot_key"],
        status=row["status"],
        event_id=row["event_id"],
        content_id=row["content_id"],
        detail=row["detail"],
        attempt_count=int(row["attempt_count"]),
        started_at=row["started_at"],
        heartbeat_at=row["heartbeat_at"],
        finished_at=row["finished_at"],
    )


def _log(row: sqlite3.Row) -> AgentLog:
    return AgentLog(
        id=row["id"],
        client_id=row["client_id"],
        run_id=row["run_id"],
        agent_name=row["agent_name"],
        status=row["status"],
        detail=row["detail"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=row["duration_ms"],
    )


def _selection(row: sqlite3.Row) -> EventSelection:
    return EventSelection(
        id=row["id"],
        client_id=row["client_id"],
        event_id=row["event_id"],
        production_date=row["production_date"],
        rank=int(row["rank"]),
        importance_score=float(row["importance_score"]),
        story_class=row["story_class"],
        created_at=row["created_at"],
    )


def _selection_rows(
    connection: sqlite3.Connection,
    client_id: str,
    production_date: str,
) -> list[EventSelection]:
    rows = connection.execute(
        """
        SELECT id, client_id, event_id, production_date, rank,
               importance_score, story_class, created_at
        FROM event_selections
        WHERE client_id = ? AND production_date = ?
        ORDER BY rank
        """,
        (client_id, production_date),
    ).fetchall()
    return [_selection(row) for row in rows]


def _notification(row: sqlite3.Row) -> NotificationRecord:
    return NotificationRecord(
        id=row["id"],
        client_id=row["client_id"],
        provider=row["provider"],
        status=row["status"],
        subject=row["subject"],
        body=row["body"],
        content_id=row["content_id"],
        created_at=row["created_at"],
        sent_at=row["sent_at"],
        detail=row["detail"],
    )
