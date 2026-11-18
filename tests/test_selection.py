"""Incremental daily selection history."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.database.models import SelectionCandidate
from app.database.repository import NewsReelsRepository
from tests.support import NOW, event_input


def _seed(repository: NewsReelsRepository, count: int) -> list[str]:
    identifiers = []
    for index in range(count):
        event = repository.insert_event(
            event_input(
                event_fingerprint=f"event-{index}",
                title_fingerprint=f"title-{index}",
                title=f"Story {index}",
            ),
            now=NOW,
        )
        identifiers.append(event.id)
    return identifiers


def _candidates(identifiers: list[str], scores: list[float] | None = None) -> list[SelectionCandidate]:
    chosen = scores or [0.8] * len(identifiers)
    return [
        SelectionCandidate(event_id, score, "major")
        for event_id, score in zip(identifiers, chosen, strict=True)
    ]


def test_same_day_run_fills_only_missing_ranks(repository: NewsReelsRepository) -> None:
    identifiers = _seed(repository, 3)
    first = repository.fill_daily_selections(
        client_id="default",
        production_date="2026-11-18",
        limit=3,
        candidates=_candidates(identifiers[:1]),
        now=NOW,
    )
    assert [row.rank for row in first] == [1]
    second = repository.fill_daily_selections(
        client_id="default",
        production_date="2026-11-18",
        limit=3,
        candidates=_candidates(identifiers),
        now=NOW + timedelta(hours=1),
    )
    assert [row.event_id for row in second] == identifiers
    assert second[0].id == first[0].id
    assert second[0].created_at == first[0].created_at


def test_a_full_day_keeps_existing_rows(repository: NewsReelsRepository) -> None:
    identifiers = _seed(repository, 4)
    stored = repository.fill_daily_selections(
        client_id="default",
        production_date="2026-11-18",
        limit=3,
        candidates=_candidates(identifiers[:3], [0.6, 0.6, 0.6]),
        now=NOW,
    )
    again = repository.fill_daily_selections(
        client_id="default",
        production_date="2026-11-18",
        limit=3,
        candidates=_candidates([identifiers[3], *identifiers[:3]], [0.99, 0.6, 0.6, 0.6]),
        now=NOW + timedelta(hours=2),
    )
    assert [row.event_id for row in again] == [row.event_id for row in stored]


def test_a_previous_day_selection_is_not_selected_again(repository: NewsReelsRepository) -> None:
    identifiers = _seed(repository, 2)
    repository.fill_daily_selections(
        client_id="default",
        production_date="2026-11-17",
        limit=3,
        candidates=_candidates(identifiers[:1]),
        now=NOW - timedelta(days=1),
    )
    today = repository.fill_daily_selections(
        client_id="default",
        production_date="2026-11-18",
        limit=3,
        candidates=_candidates(identifiers),
        now=NOW,
    )
    assert [row.event_id for row in today] == [identifiers[1]]


def test_processed_events_and_generated_content_are_excluded(repository: NewsReelsRepository) -> None:
    identifiers = _seed(repository, 4)
    database = sqlite3.connect(repository.path)
    database.execute("UPDATE news_events SET state = 'COMPLETED' WHERE id = ?", (identifiers[0],))
    database.execute("UPDATE news_events SET state = 'FAILED' WHERE id = ?", (identifiers[1],))
    database.execute("UPDATE news_events SET state = 'SELECTED' WHERE id = ?", (identifiers[2],))
    database.execute(
        """
        INSERT INTO generated_content (
            id, client_id, event_id, production_date, slot_key, state,
            attempt_count, created_at, updated_at
        ) VALUES ('content-1', 'default', ?, '2026-11-18', '09:00', 'SELECTED', 0, ?, ?)
        """,
        (identifiers[3], NOW.isoformat(), NOW.isoformat()),
    )
    database.commit()
    database.close()
    extra = repository.insert_event(
        event_input(event_fingerprint="event-open", title_fingerprint="title-open", title="Open story"),
        now=NOW,
    )
    selected = repository.fill_daily_selections(
        client_id="default",
        production_date="2026-11-18",
        limit=3,
        candidates=_candidates([*identifiers, extra.id]),
        now=NOW,
    )
    assert [row.event_id for row in selected] == [extra.id]


def test_configured_limit_stops_the_fill(repository: NewsReelsRepository) -> None:
    identifiers = _seed(repository, 5)
    selected = repository.fill_daily_selections(
        client_id="default",
        production_date="2026-11-18",
        limit=2,
        candidates=_candidates(identifiers),
        now=NOW,
    )
    assert [row.rank for row in selected] == [1, 2]
    assert len({row.event_id for row in selected}) == 2


def test_limit_zero_selects_nothing(repository: NewsReelsRepository) -> None:
    identifiers = _seed(repository, 2)
    assert repository.fill_daily_selections(
        client_id="default",
        production_date="2026-11-18",
        limit=0,
        candidates=_candidates(identifiers),
        now=NOW,
    ) == []


def test_limit_above_the_schema_ceiling_is_rejected(repository: NewsReelsRepository) -> None:
    with pytest.raises(ValueError):
        repository.fill_daily_selections(
            client_id="default",
            production_date="2026-11-18",
            limit=25,
            candidates=[],
            now=datetime.now(timezone.utc),
        )
