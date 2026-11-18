-- Phase 1 schema.
-- News events and generated reels are append-only during normal operation.
-- Deduplication depends on this history surviving process restarts.

CREATE TABLE clients (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL,
    daily_reel_limit INTEGER NOT NULL CHECK (daily_reel_limit >= 0),
    created_at TEXT NOT NULL
);

CREATE TABLE news_events (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id),
    event_fingerprint TEXT NOT NULL,
    block_key TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    title_fingerprint TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    entities_json TEXT NOT NULL DEFAULT '[]',
    event_description TEXT NOT NULL DEFAULT '',
    first_published_at TEXT,
    last_published_at TEXT,
    first_discovered_at TEXT NOT NULL,
    source_urls_json TEXT NOT NULL DEFAULT '[]',
    article_count INTEGER NOT NULL DEFAULT 0 CHECK (article_count >= 0),
    importance_score REAL CHECK (
        importance_score IS NULL OR (importance_score >= 0 AND importance_score <= 1)
    ),
    importance_breakdown_json TEXT,
    story_class TEXT CHECK (
        story_class IS NULL OR story_class IN (
            'breaking', 'major', 'minor_update', 'opinion', 'duplicate'
        )
    ),
    state TEXT NOT NULL CHECK (
        state IN (
            'DISCOVERED',
            'SELECTED',
            'SCRIPT_GENERATED',
            'IMAGES_GENERATED',
            'AUDIO_GENERATED',
            'VIDEO_RENDERED',
            'COMPLETED',
            'FAILED',
            'SKIPPED'
        )
    ),
    semantic_fingerprint TEXT,
    embedding BLOB,
    UNIQUE (client_id, event_fingerprint)
);

CREATE TABLE news_articles (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id),
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    title_fingerprint TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    discovered_at TEXT NOT NULL,
    language TEXT,
    image_url TEXT,
    simhash TEXT,
    entities_json TEXT NOT NULL DEFAULT '[]',
    relation TEXT NOT NULL DEFAULT 'primary' CHECK (
        relation IN ('primary', 'duplicate', 'update')
    ),
    event_id TEXT REFERENCES news_events(id),
    raw_payload TEXT NOT NULL DEFAULT '{}',
    UNIQUE (client_id, canonical_url)
);

CREATE TABLE generated_content (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id),
    event_id TEXT NOT NULL REFERENCES news_events(id),
    production_date TEXT NOT NULL,
    slot_key TEXT NOT NULL,
    state TEXT NOT NULL CHECK (
        state IN (
            'DISCOVERED',
            'SELECTED',
            'SCRIPT_GENERATED',
            'IMAGES_GENERATED',
            'AUDIO_GENERATED',
            'VIDEO_RENDERED',
            'COMPLETED',
            'FAILED',
            'SKIPPED'
        )
    ),
    last_successful_state TEXT CHECK (
        last_successful_state IS NULL OR last_successful_state IN (
            'DISCOVERED',
            'SELECTED',
            'SCRIPT_GENERATED',
            'IMAGES_GENERATED',
            'AUDIO_GENERATED',
            'VIDEO_RENDERED',
            'COMPLETED',
            'FAILED',
            'SKIPPED'
        )
    ),
    reserved_by TEXT,
    script_json TEXT,
    image_paths_json TEXT,
    audio_path TEXT,
    audio_duration_seconds REAL,
    video_path TEXT,
    detail TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (client_id, event_id)
);

CREATE TABLE daily_production (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id),
    production_date TEXT NOT NULL,
    slot_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'SKIPPED', 'FAILED')),
    event_id TEXT REFERENCES news_events(id),
    content_id TEXT REFERENCES generated_content(id),
    detail TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    started_at TEXT,
    heartbeat_at TEXT,
    finished_at TEXT,
    UNIQUE (client_id, production_date, slot_key)
);

CREATE TABLE agent_execution_logs (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id),
    run_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('STARTED', 'SUCCEEDED', 'FAILED')),
    detail TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    duration_ms INTEGER
);

CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id),
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'SENT', 'FAILED')),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    content_id TEXT REFERENCES generated_content(id),
    created_at TEXT NOT NULL,
    sent_at TEXT,
    detail TEXT
);

CREATE TABLE app_config (
    client_id TEXT NOT NULL REFERENCES clients(id),
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (client_id, key)
);

CREATE TABLE job_locks (
    lock_name TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE INDEX idx_articles_client_published ON news_articles(client_id, published_at);
CREATE INDEX idx_articles_title_fp ON news_articles(client_id, title_fingerprint);
CREATE INDEX idx_articles_event ON news_articles(event_id);
CREATE INDEX idx_events_client_state ON news_events(client_id, state);
CREATE INDEX idx_events_title_fp ON news_events(client_id, title_fingerprint);
CREATE INDEX idx_events_block ON news_events(client_id, block_key);
CREATE INDEX idx_content_client_state ON generated_content(client_id, state);
CREATE INDEX idx_daily_client_date ON daily_production(client_id, production_date, status);
CREATE INDEX idx_agent_logs_run ON agent_execution_logs(client_id, run_id);
CREATE INDEX idx_notifications_client ON notifications(client_id, created_at);
