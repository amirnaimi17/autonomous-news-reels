-- Append-only record of events chosen for a local day.
-- A row is never updated or deleted by normal operation.
-- Rank 24 is the configuration ceiling of DAILY_REEL_LIMIT, not the daily target.

CREATE TABLE event_selections (
    id TEXT PRIMARY KEY,
    client_id TEXT NOT NULL REFERENCES clients(id),
    event_id TEXT NOT NULL REFERENCES news_events(id),
    production_date TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1 AND rank <= 24),
    importance_score REAL NOT NULL CHECK (importance_score >= 0 AND importance_score <= 1),
    story_class TEXT CHECK (
        story_class IS NULL OR story_class IN (
            'breaking', 'major', 'minor_update', 'opinion', 'duplicate'
        )
    ),
    created_at TEXT NOT NULL,
    UNIQUE (client_id, event_id),
    UNIQUE (client_id, production_date, rank)
);

CREATE INDEX idx_event_selections_day
    ON event_selections (client_id, production_date, rank);
