"""Persistence, canonical URL identity, and restart survival."""

import threading
from datetime import timedelta

import pytest

from app.core.exceptions import (
    ArticleAlreadyLinkedError,
    DuplicateEventError,
    DuplicateStoryError,
    InvalidStateTransitionError,
    PersistenceError,
)
from app.database.repository import NewsReelsRepository
from app.database.state import allowed_targets
from app.schemas.content import GenerationState
from tests.support import NOW, article_input, event_input


def test_migration_is_idempotent_and_rows_survive_reopen(repository: NewsReelsRepository) -> None:
    assert repository.migrate() == "002"
    assert repository.migrate() == "002"
    stored, created = repository.upsert_article(article_input(), now=NOW)
    assert created is True
    reopened = NewsReelsRepository(repository.path)
    found = reopened.get_article_by_canonical_url("default", "https://bbc.com/news/world-1/")
    assert found is not None
    assert found.id == stored.id
    assert found.canonical_url == "https://bbc.com/news/world-1"
    assert found.discovered_at == stored.discovered_at


def test_tracking_parameters_do_not_create_a_second_article(repository: NewsReelsRepository) -> None:
    first, created = repository.upsert_article(article_input(), now=NOW)
    second, created_again = repository.upsert_article(
        article_input(
            source_url="https://bbc.com/news/world-1?utm_campaign=later",
            canonical_url="https://bbc.com/news/world-1?fbclid=abc",
            summary="The central bank held rates at 4.5 percent on Wednesday.",
        ),
        now=NOW,
    )
    assert created is True
    assert created_again is False
    assert second.id == first.id
    assert "Wednesday" in second.summary
    assert second.discovered_at == first.discovered_at


def test_event_fingerprint_is_unique_per_client(repository: NewsReelsRepository) -> None:
    repository.insert_event(event_input(), now=NOW)
    with pytest.raises(DuplicateEventError):
        repository.insert_event(event_input(), now=NOW)
    repository.ensure_client(
        client_id="other",
        name="Other",
        timezone_name="Europe/Berlin",
        daily_reel_limit=3,
        now=NOW,
    )
    other = repository.insert_event(event_input(client_id="other"), now=NOW)
    assert other.client_id == "other"
    assert repository.get_event_by_fingerprint("default", "event-rates") is not None


def test_article_links_once_and_updates_are_idempotent(repository: NewsReelsRepository) -> None:
    article, _ = repository.upsert_article(article_input(), now=NOW)
    event = repository.insert_event(event_input(source_urls=()), now=NOW)
    linked = repository.attach_article_to_event(article_id=article.id, event_id=event.id, relation="primary")
    again = repository.attach_article_to_event(article_id=article.id, event_id=event.id, relation="duplicate")
    assert linked.article_count == 1
    assert again.article_count == 1
    assert again.source_urls == (article.canonical_url,)
    other = repository.insert_event(event_input(event_fingerprint="other-event"), now=NOW)
    with pytest.raises(ArticleAlreadyLinkedError):
        repository.attach_article_to_event(article_id=article.id, event_id=other.id, relation="update")


def test_missing_client_is_rejected(repository: NewsReelsRepository) -> None:
    with pytest.raises(PersistenceError):
        repository.upsert_article(article_input(client_id="missing"), now=NOW)


def test_assessment_is_frozen_after_selection(repository: NewsReelsRepository) -> None:
    event = repository.insert_event(event_input(), now=NOW)
    scored = repository.update_event_assessment(
        event.id,
        importance_score=0.8,
        story_class="major",
        breakdown_json='{"impact":0.8}',
        event_description="The central bank left its policy rate unchanged.",
    )
    assert scored.importance_score == 0.8
    assert scored.story_class == "major"
    slot = repository.reserve_daily_slot(
        client_id="default",
        production_date="2026-11-18",
        slot_key="09:00",
        daily_limit=3,
        now=NOW,
        stale_after=timedelta(minutes=45),
    )
    repository.reserve_event_for_generation(
        client_id="default",
        event_id=event.id,
        production_date="2026-11-18",
        slot_key=slot.slot_key,
        owner="run-1",
        now=NOW,
    )
    with pytest.raises(InvalidStateTransitionError):
        repository.update_event_assessment(
            event.id,
            importance_score=0.1,
            story_class="minor_update",
            breakdown_json=None,
        )


def test_title_fingerprint_lookup_and_config_roundtrip(repository: NewsReelsRepository) -> None:
    event = repository.insert_event(event_input(), now=NOW)
    found = repository.list_events_by_title_fingerprint("default", "rates-fingerprint")
    assert [item.id for item in found] == [event.id]
    repository.set_config("default", "last_run", {"slot": "09:00"}, NOW)
    assert repository.get_config("default", "last_run") == {"slot": "09:00"}


def test_agent_log_and_notification_are_stored(repository: NewsReelsRepository) -> None:
    started = repository.start_agent_run(
        client_id="default",
        run_id="run-1",
        agent_name="news_research",
        now=NOW,
    )
    finished = repository.finish_agent_run(
        started.id,
        status="SUCCEEDED",
        now=NOW + timedelta(seconds=2),
        detail="5 articles",
    )
    assert finished.status == "SUCCEEDED"
    assert finished.duration_ms == 2000
    with pytest.raises(InvalidStateTransitionError):
        repository.finish_agent_run(started.id, status="FAILED", now=NOW)
    note = repository.record_notification(
        client_id="default",
        provider="log",
        status="SENT",
        subject="Reel ready",
        body="Central bank holds rates",
        now=NOW,
    )
    assert note.status == "SENT"
    assert note.sent_at is not None


def test_job_lock_excludes_a_second_owner_until_it_expires(repository: NewsReelsRepository) -> None:
    assert repository.acquire_job_lock("workflow:default", "owner-a", NOW, timedelta(minutes=5))
    assert repository.acquire_job_lock("workflow:default", "owner-a", NOW, timedelta(minutes=5))
    assert not repository.acquire_job_lock("workflow:default", "owner-b", NOW, timedelta(minutes=5))
    assert repository.refresh_job_lock("workflow:default", "owner-a", NOW, timedelta(minutes=5))
    assert not repository.refresh_job_lock("workflow:default", "owner-b", NOW, timedelta(minutes=5))
    later = NOW + timedelta(minutes=6)
    assert repository.acquire_job_lock("workflow:default", "owner-b", later, timedelta(minutes=5))
    assert repository.release_job_lock("workflow:default", "owner-b")
    assert not repository.release_job_lock("workflow:default", "owner-b")


def test_completed_state_has_no_exit() -> None:
    assert allowed_targets(GenerationState.COMPLETED, GenerationState.COMPLETED) == frozenset()
    failed = allowed_targets(GenerationState.FAILED, GenerationState.SCRIPT_GENERATED)
    assert GenerationState.IMAGES_GENERATED in failed
    assert GenerationState.AUDIO_GENERATED not in failed


def test_concurrent_event_reservation_creates_one_reel(repository: NewsReelsRepository) -> None:
    event = repository.insert_event(event_input(), now=NOW)
    repository.reserve_daily_slot(
        client_id="default",
        production_date="2026-11-18",
        slot_key="09:00",
        daily_limit=3,
        now=NOW,
        stale_after=timedelta(minutes=45),
    )
    barrier = threading.Barrier(2)
    results: list[str] = []

    def reserve(owner: str) -> None:
        local = NewsReelsRepository(repository.path)
        barrier.wait()
        try:
            content = local.reserve_event_for_generation(
                client_id="default",
                event_id=event.id,
                production_date="2026-11-18",
                slot_key="09:00",
                owner=owner,
                now=NOW,
            )
            results.append(f"ok:{content.id}")
        except DuplicateStoryError:
            results.append("duplicate")

    threads = [threading.Thread(target=reserve, args=(f"owner-{index}",)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(item.startswith("ok:") for item in results) == 1
    assert results.count("duplicate") == 1
