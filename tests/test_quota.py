"""Daily quota, slot recovery, and the generation state machine."""

from datetime import timedelta

import pytest

from app.core.exceptions import (
    DuplicateStoryError,
    InvalidStateTransitionError,
    PersistenceError,
    QuotaExceededError,
    SlotUnavailableError,
)
from app.database.repository import NewsReelsRepository
from app.schemas.content import GenerationState
from tests.support import NOW, STALE, event_input


def _reserve(
    repository: NewsReelsRepository,
    slot_key: str,
    *,
    limit: int = 3,
    now=NOW,
):
    return repository.reserve_daily_slot(
        client_id="default",
        production_date="2026-11-18",
        slot_key=slot_key,
        daily_limit=limit,
        now=now,
        stale_after=STALE,
    )


def _bind(repository: NewsReelsRepository, event_id: str, slot_key: str, owner: str, now=NOW):
    return repository.reserve_event_for_generation(
        client_id="default",
        event_id=event_id,
        production_date="2026-11-18",
        slot_key=slot_key,
        owner=owner,
        now=now,
    )


def _complete(repository: NewsReelsRepository, content_id: str, now=NOW):
    repository.transition_generation_state(
        content_id,
        GenerationState.SCRIPT_GENERATED,
        now,
        script_json='{"grounded":true}',
    )
    repository.transition_generation_state(
        content_id,
        GenerationState.IMAGES_GENERATED,
        now,
        image_paths_json='["slide.ppm"]',
    )
    repository.transition_generation_state(
        content_id,
        GenerationState.AUDIO_GENERATED,
        now,
        audio_path="voice.wav",
        audio_duration_seconds=12,
    )
    repository.transition_generation_state(
        content_id,
        GenerationState.VIDEO_RENDERED,
        now,
        video_path="reel.mp4",
    )
    return repository.transition_generation_state(
        content_id,
        GenerationState.COMPLETED,
        now,
        video_path="reel.mp4",
    )


def test_three_completed_reels_block_another_slot(repository: NewsReelsRepository) -> None:
    for index, slot_key in enumerate(("09:00", "14:00", "19:00")):
        _reserve(repository, slot_key)
        event = repository.insert_event(event_input(event_fingerprint=f"event-{index}"), now=NOW)
        content = _bind(repository, event.id, slot_key, f"run-{index}")
        finished = _complete(repository, content.id)
        assert finished.state == GenerationState.COMPLETED.value
    assert repository.count_completed_reels("default", "2026-11-18") == 3
    with pytest.raises(QuotaExceededError):
        _reserve(repository, "21:00")


def test_a_failure_or_a_shortage_does_not_count_as_a_reel(repository: NewsReelsRepository) -> None:
    morning = _reserve(repository, "09:00")
    skipped = repository.skip_unbound_slot(morning.id, "insufficient_qualifying_news", NOW)
    assert skipped.status == "SKIPPED"
    with pytest.raises(SlotUnavailableError):
        _reserve(repository, "09:00")

    afternoon = _reserve(repository, "14:00")
    event = repository.insert_event(event_input(), now=NOW)
    content = _bind(repository, event.id, afternoon.slot_key, "run-1")
    failed = repository.transition_generation_state(
        content.id,
        GenerationState.FAILED,
        NOW,
        detail="speech provider timed out",
    )
    assert failed.state == GenerationState.FAILED.value
    assert repository.count_completed_reels("default", "2026-11-18") == 0
    evening = _reserve(repository, "19:00")
    assert evening.status == "RUNNING"


def test_zero_limit_reserves_nothing(repository: NewsReelsRepository) -> None:
    with pytest.raises(QuotaExceededError):
        _reserve(repository, "09:00", limit=0)


def test_a_running_slot_blocks_a_second_slot_until_it_is_stale(repository: NewsReelsRepository) -> None:
    _reserve(repository, "09:00")
    with pytest.raises(SlotUnavailableError):
        _reserve(repository, "14:00")
    later = NOW + timedelta(hours=2)
    resumed = _reserve(repository, "14:00", now=later)
    assert resumed.slot_key == "14:00"
    morning = repository.list_daily_production("default", "2026-11-18")[0]
    assert morning.slot_key == "09:00"
    assert morning.status == "FAILED"
    assert morning.detail == "slot heartbeat expired"


def test_stale_slot_reopens_the_same_story(repository: NewsReelsRepository) -> None:
    slot = _reserve(repository, "09:00")
    event = repository.insert_event(event_input(), now=NOW)
    content = _bind(repository, event.id, "09:00", "run-1")
    repository.transition_generation_state(
        content.id,
        GenerationState.SCRIPT_GENERATED,
        NOW,
        script_json='{"grounded":true}',
    )
    later = NOW + timedelta(hours=2)
    reopened = _reserve(repository, "09:00", now=later)
    assert reopened.id == slot.id
    assert reopened.attempt_count == 2
    crashed = repository.get_content(content.id)
    assert crashed is not None
    assert crashed.state == GenerationState.FAILED.value
    assert crashed.last_successful_state == GenerationState.SCRIPT_GENERATED.value
    resumed = _bind(repository, event.id, "09:00", "run-2", now=later)
    assert resumed.id == content.id
    assert resumed.attempt_count == 2
    moved = repository.transition_generation_state(
        resumed.id,
        GenerationState.IMAGES_GENERATED,
        later,
        image_paths_json='["slide.ppm"]',
    )
    assert moved.state == GenerationState.IMAGES_GENERATED.value
    assert repository.get_event(event.id).state == GenerationState.IMAGES_GENERATED.value  # type: ignore[union-attr]


def test_a_slot_cannot_switch_stories_or_repeat_a_finished_event(repository: NewsReelsRepository) -> None:
    _reserve(repository, "09:00")
    first = repository.insert_event(event_input(event_fingerprint="one"), now=NOW)
    second = repository.insert_event(event_input(event_fingerprint="two"), now=NOW)
    content = _bind(repository, first.id, "09:00", "run-1")
    with pytest.raises(PersistenceError):
        _bind(repository, second.id, "09:00", "run-1")
    _complete(repository, content.id)
    _reserve(repository, "14:00")
    with pytest.raises(DuplicateStoryError):
        _bind(repository, first.id, "14:00", "run-2")


def test_generation_cannot_skip_ahead_or_leave_a_completed_reel(repository: NewsReelsRepository) -> None:
    _reserve(repository, "09:00")
    event = repository.insert_event(event_input(), now=NOW)
    content = _bind(repository, event.id, "09:00", "run-1")
    with pytest.raises(InvalidStateTransitionError):
        repository.transition_generation_state(
            content.id,
            GenerationState.AUDIO_GENERATED,
            NOW,
            audio_path="voice.wav",
            audio_duration_seconds=10,
        )
    with pytest.raises(PersistenceError):
        repository.transition_generation_state(content.id, GenerationState.SCRIPT_GENERATED, NOW)
    finished = _complete(repository, content.id)
    with pytest.raises(InvalidStateTransitionError):
        repository.transition_generation_state(
            finished.id,
            GenerationState.FAILED,
            NOW,
            detail="too late",
        )


def test_concurrent_slot_reservation_allows_one_winner(repository: NewsReelsRepository) -> None:
    import threading

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt() -> None:
        local = NewsReelsRepository(repository.path)
        barrier.wait()
        try:
            local.reserve_daily_slot(
                client_id="default",
                production_date="2026-11-18",
                slot_key="09:00",
                daily_limit=3,
                now=NOW,
                stale_after=STALE,
            )
            outcomes.append("ok")
        except SlotUnavailableError:
            outcomes.append("busy")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["busy", "ok"]


def test_heartbeat_extends_a_running_slot(repository: NewsReelsRepository) -> None:
    slot = _reserve(repository, "09:00")
    beaten = repository.heartbeat_slot(slot.id, NOW + timedelta(minutes=40))
    assert beaten.heartbeat_at != slot.heartbeat_at
    with pytest.raises(SlotUnavailableError):
        _reserve(repository, "14:00", now=NOW + timedelta(minutes=40))
