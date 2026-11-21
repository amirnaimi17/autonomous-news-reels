"""SQLite lifecycle store for generated Reels.

This database is separate from ``data/news_reels.db``. Timestamps are UTC.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS generation_attempts (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    target_page TEXT NOT NULL,
    slot_local TEXT,
    status TEXT NOT NULL,
    reel_id TEXT,
    message TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS reels (
    reel_id TEXT PRIMARY KEY,
    story_fingerprint TEXT NOT NULL UNIQUE,
    target_page TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    affected_audience TEXT NOT NULL DEFAULT '',
    editorial_angle TEXT NOT NULL DEFAULT '',
    narration_fa TEXT NOT NULL DEFAULT '',
    caption_fa TEXT NOT NULL DEFAULT '',
    storyboard_json TEXT NOT NULL DEFAULT '{}',
    video_path TEXT NOT NULL DEFAULT '',
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    checksum_sha256 TEXT,
    local_status TEXT NOT NULL,
    production_delivery_id TEXT,
    scheduled_for TEXT,
    facts_checked_at TEXT,
    generation_started_at TEXT NOT NULL,
    generation_finished_at TEXT,
    error_message TEXT NOT NULL DEFAULT '',
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reel_sources (
    id INTEGER PRIMARY KEY,
    reel_id TEXT NOT NULL REFERENCES reels(reel_id),
    url TEXT NOT NULL,
    publisher TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    verified_at TEXT,
    excerpt TEXT NOT NULL DEFAULT '',
    UNIQUE (reel_id, url)
);

CREATE TABLE IF NOT EXISTS reel_assets (
    id INTEGER PRIMARY KEY,
    reel_id TEXT NOT NULL REFERENCES reels(reel_id),
    path TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    license_name TEXT NOT NULL DEFAULT '',
    license_url TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS reel_audio (
    id INTEGER PRIMARY KEY,
    reel_id TEXT NOT NULL REFERENCES reels(reel_id),
    path TEXT NOT NULL,
    provider TEXT NOT NULL,
    voice_id TEXT NOT NULL DEFAULT '',
    model_id TEXT NOT NULL DEFAULT '',
    speed REAL NOT NULL DEFAULT 1.0,
    duration_seconds REAL
);

CREATE TABLE IF NOT EXISTS reel_qa (
    id INTEGER PRIMARY KEY,
    reel_id TEXT NOT NULL REFERENCES reels(reel_id),
    kind TEXT NOT NULL,
    passed INTEGER NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reel_costs (
    id INTEGER PRIMARY KEY,
    reel_id TEXT NOT NULL REFERENCES reels(reel_id),
    provider TEXT NOT NULL,
    kind TEXT NOT NULL,
    usd REAL NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reel_uploads (
    id INTEGER PRIMARY KEY,
    reel_id TEXT NOT NULL REFERENCES reels(reel_id),
    attempted_at TEXT NOT NULL,
    url TEXT NOT NULL,
    http_status INTEGER,
    response_json TEXT NOT NULL DEFAULT '{}',
    error_message TEXT NOT NULL DEFAULT '',
    success INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS reel_errors (
    id INTEGER PRIMARY KEY,
    reel_id TEXT,
    attempt_id INTEGER,
    recorded_at TEXT NOT NULL,
    stage TEXT NOT NULL,
    message TEXT NOT NULL,
    retryable INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_reels_status ON reels(local_status, updated_at);
CREATE INDEX IF NOT EXISTS idx_attempts_started ON generation_attempts(started_at);
CREATE INDEX IF NOT EXISTS idx_costs_recorded ON reel_costs(recorded_at);
CREATE INDEX IF NOT EXISTS idx_errors_reel ON reel_errors(reel_id, recorded_at);

CREATE TABLE IF NOT EXISTS pages (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    page_id INTEGER NOT NULL REFERENCES pages(id),
    reel_id TEXT NOT NULL UNIQUE REFERENCES reels(reel_id),
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    scheduled_for TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS post_videos (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    path TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL DEFAULT '',
    duration_seconds REAL,
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (post_id, path)
);

CREATE TABLE IF NOT EXISTS cron_job_logs (
    id INTEGER PRIMARY KEY,
    job_name TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_cron_created ON cron_job_logs(created_at);
"""


def utc_now(now: datetime | None = None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(timezone.utc).isoformat()


class ReelStore:
    """Migrations and queries inside the single project database, ``data/news_reels.db``."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                ("001_reel_lifecycle", utc_now()),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                ("002_posts_and_cron", utc_now()),
            )

    def start_attempt(self, *, target_page: str, slot_local: str, now: datetime) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO generation_attempts
                    (started_at, target_page, slot_local, status, message)
                VALUES (?, ?, ?, 'started', '')
                """,
                (utc_now(now), target_page, slot_local),
            )
            return int(cursor.lastrowid)

    def finish_attempt(
        self,
        attempt_id: int,
        *,
        status: str,
        message: str,
        reel_id: str = "",
        detail: dict | None = None,
        now: datetime | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE generation_attempts
                SET finished_at = ?, status = ?, reel_id = ?, message = ?, detail_json = ?
                WHERE id = ?
                """,
                (utc_now(now), status, reel_id, message, json.dumps(detail or {}, ensure_ascii=False), attempt_id),
            )

    def get_by_fingerprint(self, fingerprint: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                "SELECT * FROM reels WHERE story_fingerprint = ?",
                (fingerprint,),
            ).fetchone()

    def get(self, reel_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM reels WHERE reel_id = ?", (reel_id,)).fetchone()

    def upsert_reel(self, row: dict) -> None:
        columns = [
            "reel_id",
            "story_fingerprint",
            "target_page",
            "title",
            "category",
            "affected_audience",
            "editorial_angle",
            "narration_fa",
            "caption_fa",
            "storyboard_json",
            "video_path",
            "duration_seconds",
            "width",
            "height",
            "checksum_sha256",
            "local_status",
            "production_delivery_id",
            "scheduled_for",
            "facts_checked_at",
            "generation_started_at",
            "generation_finished_at",
            "error_message",
            "retry_count",
            "created_at",
            "updated_at",
        ]
        values = [row.get(column) for column in columns]
        placeholders = ", ".join("?" for _ in columns)
        assignments = ", ".join(f"{column} = excluded.{column}" for column in columns if column != "reel_id")
        with self.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO reels ({", ".join(columns)})
                VALUES ({placeholders})
                ON CONFLICT(reel_id) DO UPDATE SET {assignments}
                """,
                values,
            )

    def add_source(self, reel_id: str, *, url: str, publisher: str, title: str, verified_at: str, excerpt: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reel_sources (reel_id, url, publisher, title, verified_at, excerpt)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(reel_id, url) DO UPDATE SET
                    publisher = excluded.publisher,
                    title = excluded.title,
                    verified_at = excluded.verified_at,
                    excerpt = excluded.excerpt
                """,
                (reel_id, url, publisher, title, verified_at, excerpt),
            )

    def add_asset(self, reel_id: str, asset: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reel_assets
                    (reel_id, path, source_url, author, license_name, license_url, role)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reel_id,
                    asset.get("path", ""),
                    asset.get("source_url", ""),
                    asset.get("author", ""),
                    asset.get("license_name", ""),
                    asset.get("license_url", ""),
                    asset.get("role", ""),
                ),
            )

    def add_audio(self, reel_id: str, audio: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reel_audio
                    (reel_id, path, provider, voice_id, model_id, speed, duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reel_id,
                    audio["path"],
                    audio["provider"],
                    audio.get("voice_id", ""),
                    audio.get("model_id", ""),
                    audio.get("speed", 1.0),
                    audio.get("duration_seconds"),
                ),
            )

    def add_qa(self, reel_id: str, *, kind: str, passed: bool, detail: dict, checked_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reel_qa (reel_id, kind, passed, detail_json, checked_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (reel_id, kind, 1 if passed else 0, json.dumps(detail, ensure_ascii=False), checked_at),
            )

    def add_cost(self, reel_id: str, *, provider: str, kind: str, usd: float, detail: dict, recorded_at: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reel_costs (reel_id, provider, kind, usd, detail_json, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (reel_id, provider, kind, usd, json.dumps(detail, ensure_ascii=False), recorded_at),
            )

    def add_upload(self, reel_id: str, *, url: str, http_status: int | None, response: dict, error: str, success: bool, now: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reel_uploads
                    (reel_id, attempted_at, url, http_status, response_json, error_message, success)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (reel_id, utc_now(now), url, http_status, json.dumps(response, ensure_ascii=False), error, 1 if success else 0),
            )

    def add_error(self, *, reel_id: str, attempt_id: int | None, stage: str, message: str, retryable: bool, now: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO reel_errors (reel_id, attempt_id, recorded_at, stage, message, retryable)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (reel_id, attempt_id, utc_now(now), stage, message, 1 if retryable else 0),
            )

    def spent_between(self, start: datetime, end: datetime) -> float:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(usd), 0) AS total
                FROM reel_costs
                WHERE kind = 'actual' AND recorded_at >= ? AND recorded_at < ?
                """,
                (utc_now(start), utc_now(end)),
            ).fetchone()
        return float(row["total"])

    def sources_for(self, reel_id: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute("SELECT * FROM reel_sources WHERE reel_id = ? ORDER BY id", (reel_id,)))

    def assets_for(self, reel_id: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute("SELECT * FROM reel_assets WHERE reel_id = ? ORDER BY id", (reel_id,)))

    def qa_for(self, reel_id: str) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute("SELECT * FROM reel_qa WHERE reel_id = ? ORDER BY id", (reel_id,)))

    def recent_attempts(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    "SELECT * FROM generation_attempts ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            )

    def recent_reels(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute("SELECT * FROM reels ORDER BY updated_at DESC LIMIT ?", (limit,)))

    def ensure_page(self, name: str, *, username: str = "", now: datetime | None = None) -> int:
        stamp = utc_now(now)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO pages (name, username, status, created_at)
                VALUES (?, ?, 'active', ?)
                ON CONFLICT(name) DO UPDATE SET username = excluded.username
                """,
                (name, username, stamp),
            )
            row = connection.execute("SELECT id FROM pages WHERE name = ?", (name,)).fetchone()
        return int(row["id"])

    def upsert_post(self, *, page_id: int, reel_id: str, title: str, description: str, status: str, scheduled_for: str | None, now: datetime) -> int:
        stamp = utc_now(now)
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO posts (page_id, reel_id, title, description, status, scheduled_for, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reel_id) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    status = excluded.status,
                    scheduled_for = excluded.scheduled_for,
                    updated_at = excluded.updated_at
                """,
                (page_id, reel_id, title, description, status, scheduled_for, stamp, stamp),
            )
            row = connection.execute("SELECT id FROM posts WHERE reel_id = ?", (reel_id,)).fetchone()
        return int(row["id"])

    def add_video(self, *, post_id: int, path: str, checksum: str, duration: float | None, width: int | None, height: int | None, status: str, now: datetime) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO post_videos
                    (post_id, path, checksum_sha256, duration_seconds, width, height, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(post_id, path) DO UPDATE SET
                    checksum_sha256 = excluded.checksum_sha256,
                    duration_seconds = excluded.duration_seconds,
                    width = excluded.width,
                    height = excluded.height,
                    status = excluded.status
                """,
                (post_id, path, checksum, duration, width, height, status, utc_now(now)),
            )

    def add_cron_log(self, *, job_name: str, status: str, message: str, detail: dict | None = None, now: datetime | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO cron_job_logs (job_name, status, message, detail_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (job_name, status, message, json.dumps(detail or {}, ensure_ascii=False), utc_now(now)),
            )

    def recent_posts(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    """
                    SELECT posts.*, pages.name AS page_name
                    FROM posts JOIN pages ON pages.id = posts.page_id
                    ORDER BY posts.updated_at DESC LIMIT ?
                    """,
                    (limit,),
                )
            )

    def recent_cron_logs(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute("SELECT * FROM cron_job_logs ORDER BY id DESC LIMIT ?", (limit,)))

    def videos_for(self, post_id: int) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute("SELECT * FROM post_videos WHERE post_id = ? ORDER BY id", (post_id,)))

    def set_status(self, reel_id: str, status: str, *, error: str = "", delivery_id: str | None = None, now: datetime | None = None) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE reels
                SET local_status = ?, error_message = ?, production_delivery_id = COALESCE(?, production_delivery_id),
                    updated_at = ?
                WHERE reel_id = ?
                """,
                (status, error, delivery_id, utc_now(now), reel_id),
            )
