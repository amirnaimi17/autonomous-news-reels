"""One generation attempt. At most one Reel, and none when the story is unfit.

The silent voice generator and the solid-color image provider are not used.
Paid narration and paid images stay behind ``paid_generation``.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.reels.config import ReelConfig
from app.reels.store import ReelStore, utc_now
from app.services.dedup.url import canonicalize_url
from app.services.news.accuracy import deutschlandticket_accuracy_errors
from app.services.news.audience import audience_filter
from app.services.news.editorial import editorial_approves

TERMINAL = {"packaged", "queued", "uploaded"}
RETRYABLE = {"failed", "blocked_paid"}


@dataclass
class Candidate:
    title: str
    summary: str
    url: str
    publisher: str
    published_at: datetime
    category: str = ""


@dataclass
class StageResult:
    status: str
    message: str
    reel_id: str = ""
    detail: dict = field(default_factory=dict)


def story_fingerprint(url: str, title: str) -> str:
    canonical = canonicalize_url(url)
    folded = " ".join(title.casefold().split())
    return hashlib.sha256(f"{canonical}\n{folded}".encode("utf-8")).hexdigest()


def slot_decision(now: datetime, config: ReelConfig, *, scheduled: bool) -> str:
    """Return ok, manual, outside_slot, or missed_slot.

    A scheduled run that starts after the grace window is a late catch-up.
    Those runs do not generate news that was already stale by the time the
    computer came back.
    """

    local = now.astimezone(config.zone)
    if local.hour not in config.generation_hours:
        return "manual" if not scheduled else "outside_slot"
    if scheduled and local.minute > config.slot_grace_minutes:
        return "missed_slot"
    return "ok"


def _assessment(candidate: Candidate, audience: str) -> dict:
    return {
        "decision": "approve" if audience == "clear" else "reject",
        "affected_audience": "Iranians living in Germany",
        "practical_relevance": candidate.summary.strip(),
        "publication_reason": f"The story matches a household topic: {candidate.title.strip()}",
        "evidence_urls": [candidate.url],
    }


def _assessment_from_rank(candidate: Candidate, ranked, audience_label: str) -> dict:
    relevance = (ranked.relevance or ranked.practical_impact or candidate.summary).strip()
    reason = (
        ranked.audience_interest
        or ranked.newsworthiness
        or f"Selected for {audience_label}: {candidate.title.strip()}"
    ).strip()
    return {
        "decision": "approve",
        "affected_audience": audience_label,
        "practical_relevance": relevance,
        "publication_reason": reason,
        "evidence_urls": [candidate.url],
    }


def _is_duplicate(store: ReelStore, candidate: Candidate) -> bool:
    fingerprint = story_fingerprint(candidate.url, candidate.title)
    existing = store.get_by_fingerprint(fingerprint)
    if existing is None:
        return False
    if existing["local_status"] in TERMINAL:
        return True
    if existing["local_status"] == "rejected":
        return True
    if existing["local_status"] in RETRYABLE and int(existing["retry_count"]) >= 3:
        return True
    return False


def _eligible_for_ranking(
    candidates: list[Candidate],
    store: ReelStore,
    now: datetime,
    window_hours: int,
) -> tuple[list[Candidate], str]:
    """Fresh, non-duplicate candidates with basic source shape. No keyword gate."""

    window_start = now.astimezone(timezone.utc) - timedelta(hours=window_hours)
    ranked = sorted(candidates, key=lambda item: item.published_at, reverse=True)
    eligible: list[Candidate] = []
    saw_stale = False
    saw_duplicate = False
    saw_unverified = False
    for candidate in ranked:
        published = candidate.published_at.astimezone(timezone.utc)
        if published < window_start or published > now.astimezone(timezone.utc) + timedelta(minutes=5):
            saw_stale = True
            continue
        text = f"{candidate.title}\n{candidate.summary}"
        if not candidate.summary.strip() or not candidate.url.startswith("http"):
            saw_unverified = True
            continue
        if deutschlandticket_accuracy_errors(text):
            saw_unverified = True
            continue
        if _is_duplicate(store, candidate):
            saw_duplicate = True
            continue
        eligible.append(candidate)
    if eligible:
        return eligible, ""
    if saw_duplicate and not saw_stale and not saw_unverified:
        return [], "duplicate"
    if saw_stale and not saw_unverified:
        return [], "stale"
    if saw_unverified:
        return [], "inadequately verified"
    return [], "no story"


def select_story_keyword_queue(
    candidates: list[Candidate],
    store: ReelStore,
    now: datetime,
    window_hours: int,
) -> tuple[list[Candidate], str, dict]:
    """Legacy keyword audience filter. Returns an ordered queue of clear matches."""

    window_start = now.astimezone(timezone.utc) - timedelta(hours=window_hours)
    ranked = sorted(candidates, key=lambda item: item.published_at, reverse=True)
    saw_irrelevant = False
    saw_stale = False
    saw_duplicate = False
    queue: list[Candidate] = []
    for candidate in ranked:
        published = candidate.published_at.astimezone(timezone.utc)
        if published < window_start or published > now.astimezone(timezone.utc) + timedelta(minutes=5):
            saw_stale = True
            continue
        text = f"{candidate.title}\n{candidate.summary}"
        audience = audience_filter(text)
        if audience.result != "clear":
            saw_irrelevant = True
            continue
        if not candidate.summary.strip() or not candidate.url.startswith("http"):
            continue
        if deutschlandticket_accuracy_errors(text):
            continue
        assessment = _assessment(candidate, audience.result)
        if not editorial_approves(assessment, [candidate.url]):
            continue
        if _is_duplicate(store, candidate):
            saw_duplicate = True
            continue
        queue.append(candidate)
    if queue:
        return queue, "", {"selection": "keyword", "audience": "clear", "queue_size": len(queue)}
    if saw_duplicate and not saw_irrelevant:
        return [], "duplicate", {"selection": "keyword"}
    if saw_stale and not saw_irrelevant:
        return [], "stale", {"selection": "keyword"}
    if saw_irrelevant:
        return [], "irrelevant", {"selection": "keyword"}
    return [], "no story", {"selection": "keyword"}


def select_story_keyword(
    candidates: list[Candidate],
    store: ReelStore,
    now: datetime,
    window_hours: int,
) -> tuple[Candidate | None, str, dict]:
    """Legacy keyword audience filter. Borderline/none stay rejected as irrelevant."""

    queue, reason, detail = select_story_keyword_queue(candidates, store, now, window_hours)
    if not queue:
        return None, reason, detail
    return queue[0], "", detail


def select_story_ai_queue(
    candidates: list[Candidate],
    store: ReelStore,
    now: datetime,
    config: ReelConfig,
    *,
    rank_complete=None,
) -> tuple[list[Candidate], str, dict]:
    """Rank once and return an ordered queue of suitable, non-duplicate articles."""

    from app.services.news.editorial_rank import get_audience_profile, rank_retrieved_articles

    eligible, reason = _eligible_for_ranking(candidates, store, now, config.news_window_hours)
    if not eligible:
        return [], reason or "no story", {"selection": "ai", "eligible": 0}

    if config.editorial_rank_provider == "openai" and not config.editorial_rank_approved and rank_complete is None:
        return [], "editorial ranking not approved", {"selection": "ai", "eligible": len(eligible)}

    from app.core.exceptions import ConfigurationError, GroundingError

    profile = get_audience_profile(config.editorial_audience_id, path=config.editorial_audiences_file)
    threshold = (
        float(config.editorial_min_score)
        if config.editorial_min_score is not None
        else float(profile.min_score)
    )
    detail: dict = {"selection": "ai", "eligible": len(eligible), "min_score": threshold}
    try:
        ranking = rank_retrieved_articles(
            eligible,
            audience_id=config.editorial_audience_id,
            audiences_file=config.editorial_audiences_file,
            min_score=threshold,
            now=now,
            model=config.script_model,
            complete=rank_complete,
        )
    except (ConfigurationError, GroundingError) as exc:
        detail["ranking_error"] = str(exc)
        return [], str(exc), detail
    detail["ranking"] = ranking.as_detail()
    if ranking.status != "selected" or ranking.selected is None:
        return [], ranking.message or "no suitable article", detail

    by_url = {item.url: item for item in eligible}
    queue: list[Candidate] = []
    seen_urls: set[str] = set()

    def _append(candidate: Candidate | None, ranked_row=None) -> None:
        if candidate is None or candidate.url in seen_urls:
            return
        if _is_duplicate(store, candidate):
            return
        if ranked_row is not None:
            assessment = _assessment_from_rank(candidate, ranked_row, profile.label)
            if not editorial_approves(assessment, [candidate.url]):
                return
        seen_urls.add(candidate.url)
        queue.append(candidate)

    # Selected article first, then remaining suitable ranked rows (no second ranking call).
    chosen = by_url.get(ranking.selected.url)
    if chosen is None:
        from app.services.news.editorial_rank import assign_article_ids

        rows = assign_article_ids(eligible)
        match = next((row for row in rows if row["id"] == ranking.selected_id), None)
        chosen = match["candidate"] if match else None
    _append(chosen, ranking.selected)
    for ranked_row in ranking.top:
        if not ranked_row.suitable:
            continue
        _append(by_url.get(ranked_row.url), ranked_row)

    if not queue:
        return [], "duplicate", detail
    detail["selected"] = {
        "title": queue[0].title,
        "url": queue[0].url,
        "score": ranking.selected.score,
        "relevance": ranking.selected.relevance,
    }
    detail["queue_size"] = len(queue)
    return queue, "", detail


def select_story_ai(
    candidates: list[Candidate],
    store: ReelStore,
    now: datetime,
    config: ReelConfig,
    *,
    rank_complete=None,
) -> tuple[Candidate | None, str, dict]:
    """Rank retrieved articles with the configured editorial audience profile."""

    queue, reason, detail = select_story_ai_queue(
        candidates, store, now, config, rank_complete=rank_complete
    )
    if not queue:
        return None, reason, detail
    return queue[0], "", detail


def select_story_queue(
    candidates: list[Candidate],
    store: ReelStore,
    now: datetime,
    window_hours: int,
    *,
    config: ReelConfig | None = None,
    rank_complete=None,
) -> tuple[list[Candidate], str, dict]:
    """Return an ordered article queue for one command (ranked at most once)."""

    if config is not None and config.editorial_rank_provider == "openai":
        return select_story_ai_queue(candidates, store, now, config, rank_complete=rank_complete)
    return select_story_keyword_queue(candidates, store, now, window_hours)


def select_story(
    candidates: list[Candidate],
    store: ReelStore,
    now: datetime,
    window_hours: int,
    *,
    config: ReelConfig | None = None,
    rank_complete=None,
) -> tuple[Candidate | None, str, dict]:
    """Pick one story. Uses AI ranking when configured; otherwise keyword filter."""

    queue, reason, detail = select_story_queue(
        candidates,
        store,
        now,
        window_hours,
        config=config,
        rank_complete=rank_complete,
    )
    if not queue:
        return None, reason, detail
    return queue[0], "", detail


def _max_article_attempts(config: ReelConfig) -> int:
    """Hard cap of three article tries per command; never retries indefinitely."""

    configured = int(getattr(config, "max_attempts", 3) or 3)
    return max(1, min(3, configured))


def run_generation(
    config: ReelConfig,
    store: ReelStore,
    *,
    now: datetime,
    scheduled: bool,
    candidates: list[Candidate],
    verify_source,
    write_script,
    find_assets,
    narrate,
    render_video,
    probe_video,
    rank_complete=None,
) -> StageResult:
    """Run one command attempt, trying up to three ranked articles without re-ranking."""

    store.migrate()
    decision = slot_decision(now, config, scheduled=scheduled)
    local_slot = now.astimezone(config.zone).strftime("%Y-%m-%d %H:%M")
    attempt_id = store.start_attempt(target_page=config.target_page, slot_local=local_slot, now=now)
    if config.target_page != "almanyar":
        store.finish_attempt(attempt_id, status="rejected", message="target must be almanyar", now=now)
        return StageResult("rejected", "target must be almanyar")
    if decision in {"outside_slot", "missed_slot"}:
        message = "missed slot was not caught up" if decision == "missed_slot" else "outside the Berlin generation hours"
        store.finish_attempt(attempt_id, status="skipped", message=message, now=now)
        return StageResult("skipped", message)

    queue, reason, selection_detail = select_story_queue(
        candidates,
        store,
        now,
        config.news_window_hours,
        config=config,
        rank_complete=rank_complete,
    )
    if not queue:
        store.finish_attempt(attempt_id, status="rejected", message=reason or "no story", now=now)
        return StageResult("rejected", reason or "no story", detail=selection_detail)

    max_tries = _max_article_attempts(config)
    article_attempts: list[dict] = []
    selection_detail = dict(selection_detail)
    selection_detail["max_article_attempts"] = max_tries
    last: StageResult | None = None

    for index, candidate in enumerate(queue[:max_tries], start=1):
        selection_detail["selected"] = {
            "title": candidate.title,
            "url": candidate.url,
            "attempt_index": index,
        }
        result = _generate_one_article(
            config,
            store,
            candidate=candidate,
            now=now,
            attempt_id=attempt_id,
            selection_detail=selection_detail,
            verify_source=verify_source,
            write_script=write_script,
            find_assets=find_assets,
            narrate=narrate,
            render_video=render_video,
            probe_video=probe_video,
            finalize=False,
        )
        article_attempts.append(
            {
                "index": index,
                "title": candidate.title,
                "url": candidate.url,
                "status": result.status,
                "message": result.message,
                "reel_id": result.reel_id,
            }
        )
        selection_detail["article_attempts"] = article_attempts
        result.detail = dict(selection_detail)
        last = result
        # Terminal success / budget stop — do not keep trying more articles.
        if result.status in {"qa_passed", "blocked_paid", "queued", "packaged"}:
            store.finish_attempt(
                attempt_id,
                status=result.status,
                message=result.message,
                reel_id=result.reel_id,
                now=now,
            )
            return result
        if result.status == "rejected" and result.message == "cost limit":
            store.finish_attempt(
                attempt_id,
                status=result.status,
                message=result.message,
                reel_id=result.reel_id,
                now=now,
            )
            return result
        # rejected / failed / qa_failed → try next ranked article when available.

    assert last is not None
    store.finish_attempt(
        attempt_id,
        status=last.status,
        message=last.message,
        reel_id=last.reel_id,
        now=now,
    )
    last.detail = dict(selection_detail)
    return last


def _generate_one_article(
    config: ReelConfig,
    store: ReelStore,
    *,
    candidate: Candidate,
    now: datetime,
    attempt_id: int,
    selection_detail: dict,
    verify_source,
    write_script,
    find_assets,
    narrate,
    render_video,
    probe_video,
    finalize: bool = True,
) -> StageResult:
    """Produce one Reel for a single ranked article. Does not re-rank news."""

    def _stage(status: str, message: str, reel_id: str = "") -> StageResult:
        return StageResult(status, message, reel_id, detail=selection_detail)

    fingerprint = story_fingerprint(candidate.url, candidate.title)
    existing = store.get_by_fingerprint(fingerprint)
    reel_id = existing["reel_id"] if existing is not None else uuid.uuid4().hex
    retry_count = int(existing["retry_count"]) + 1 if existing is not None else 0
    checked = verify_source(candidate)
    if not checked.get("ok"):
        _record_rejected(
            store,
            config,
            candidate,
            reel_id,
            fingerprint,
            retry_count,
            "inadequately verified",
            attempt_id,
            now,
            finalize=finalize,
        )
        return _stage("rejected", "inadequately verified", reel_id)

    script = write_script(candidate, checked, paid_generation=config.paid_generation)
    row = _base_row(config, candidate, reel_id, fingerprint, retry_count, checked, now)
    if script.get("status") != "ready":
        row["local_status"] = "blocked_paid" if script.get("status") == "blocked_paid" else "rejected"
        row["error_message"] = script.get("message", "script refused")
        row["generation_finished_at"] = utc_now(now)
        store.upsert_reel(row)
        store.add_source(
            reel_id,
            url=candidate.url,
            publisher=candidate.publisher,
            title=candidate.title,
            verified_at=utc_now(now),
            excerpt=checked.get("excerpt", "")[:1000],
        )
        store.add_error(
            reel_id=reel_id,
            attempt_id=attempt_id,
            stage="script",
            message=row["error_message"],
            retryable=row["local_status"] == "blocked_paid",
            now=now,
        )
        if finalize:
            store.finish_attempt(
                attempt_id,
                status=row["local_status"],
                message=row["error_message"],
                reel_id=reel_id,
                now=now,
            )
        return _stage(row["local_status"], row["error_message"], reel_id)

    narration = script["narration"]
    if deutschlandticket_accuracy_errors(narration):
        _record_rejected(
            store,
            config,
            candidate,
            reel_id,
            fingerprint,
            retry_count,
            "inadequately verified",
            attempt_id,
            now,
            finalize=finalize,
        )
        return _stage("rejected", "inadequately verified", reel_id)

    try:
        assets = find_assets(candidate, script)
    except Exception as exc:
        message = str(exc) or "photograph retrieval failed"
        _record_failed(
            store,
            config,
            candidate,
            reel_id,
            fingerprint,
            retry_count,
            message,
            attempt_id,
            now,
            stage="photos",
            script=script,
            checked=checked,
            finalize=finalize,
        )
        return _stage("failed", message, reel_id)
    if not assets:
        message = "no relevant photographs"
        _record_failed(
            store,
            config,
            candidate,
            reel_id,
            fingerprint,
            retry_count,
            message,
            attempt_id,
            now,
            stage="photos",
            script=script,
            checked=checked,
            finalize=finalize,
        )
        return _stage("failed", message, reel_id)
    # Mandatory photographs: reject graphic placeholders before any paid TTS.
    graphic_kinds = {"remotion-graphic", "original-graphic", "silent-fixture"}
    if any(
        not str(asset.get("path") or "").strip()
        or str(asset.get("license_name") or "").strip().casefold() in graphic_kinds
        or str(asset.get("kind") or "").strip().casefold() in graphic_kinds
        for asset in assets
    ):
        message = "mandatory photographs missing"
        _record_failed(
            store,
            config,
            candidate,
            reel_id,
            fingerprint,
            retry_count,
            message,
            attempt_id,
            now,
            stage="photos",
            script=script,
            checked=checked,
            finalize=finalize,
        )
        return _stage("failed", message, reel_id)
    for asset in assets:
        if asset.get("kind") == "paid-image" and not config.paid_generation:
            _record_rejected(
                store,
                config,
                candidate,
                reel_id,
                fingerprint,
                retry_count,
                "paid image refused",
                attempt_id,
                now,
                finalize=finalize,
            )
            return _stage("rejected", "paid image refused", reel_id)

    estimate = float(script.get("voice_estimate_usd") or 0)
    if config.paid_generation and not _within_budget(config, store, estimate, now):
        row["local_status"] = "rejected"
        row["error_message"] = "cost limit"
        row["narration_fa"] = narration
        row["generation_finished_at"] = utc_now(now)
        store.upsert_reel(row)
        if finalize:
            store.finish_attempt(attempt_id, status="rejected", message="cost limit", reel_id=reel_id, now=now)
        return _stage("rejected", "cost limit", reel_id)

    row["narration_fa"] = narration
    row["caption_fa"] = script.get("caption", "")
    row["editorial_angle"] = script.get("angle", "")
    row["storyboard_json"] = script.get("storyboard_json", "{}")
    row["local_status"] = "scripted"
    store.upsert_reel(row)
    store.add_source(
        reel_id,
        url=candidate.url,
        publisher=candidate.publisher,
        title=candidate.title,
        verified_at=utc_now(now),
        excerpt=checked.get("excerpt", "")[:1000],
    )
    for asset in assets:
        store.add_asset(reel_id, asset)

    if not config.paid_generation:
        row["local_status"] = "blocked_paid"
        row["error_message"] = "paid generation is disabled"
        row["generation_finished_at"] = utc_now(now)
        store.upsert_reel(row)
        store.add_error(
            reel_id=reel_id,
            attempt_id=attempt_id,
            stage="voice",
            message=row["error_message"],
            retryable=True,
            now=now,
        )
        if finalize:
            store.finish_attempt(
                attempt_id, status="blocked_paid", message=row["error_message"], reel_id=reel_id, now=now
            )
        return _stage("blocked_paid", row["error_message"], reel_id)

    try:
        audio = narrate(narration, config.voice_id)
        video = render_video(script, assets, audio)
        probe = probe_video(video["path"])
    except Exception as exc:
        row["local_status"] = "failed"
        row["error_message"] = str(exc) or exc.__class__.__name__
        row["retry_count"] = retry_count
        row["generation_finished_at"] = utc_now(now)
        store.upsert_reel(row)
        store.add_error(
            reel_id=reel_id,
            attempt_id=attempt_id,
            stage="render",
            message=row["error_message"],
            retryable=True,
            now=now,
        )
        if finalize:
            store.finish_attempt(
                attempt_id, status="failed", message=row["error_message"], reel_id=reel_id, now=now
            )
        return _stage("failed", row["error_message"], reel_id)

    store.add_audio(reel_id, audio)
    store.add_cost(
        reel_id,
        provider=audio.get("provider", "elevenlabs"),
        kind="actual",
        usd=float(audio.get("usd") or estimate),
        detail={"characters": audio.get("characters", 0)},
        recorded_at=utc_now(now),
    )
    problems = _technical_problems(probe)
    passed = not problems
    store.add_qa(reel_id, kind="technical", passed=passed, detail=probe, checked_at=utc_now(now))
    store.add_qa(reel_id, kind="factual", passed=True, detail={"sources": [candidate.url]}, checked_at=utc_now(now))
    # License metadata is optional; photographic file presence is the acceptance gate.
    store.add_qa(
        reel_id,
        kind="media",
        passed=all(str(asset.get("path") or "").strip() for asset in assets),
        detail={"assets": len(assets)},
        checked_at=utc_now(now),
    )
    store.add_qa(
        reel_id,
        kind="audio",
        passed=bool(audio.get("duration_seconds")),
        detail={"duration_seconds": audio.get("duration_seconds")},
        checked_at=utc_now(now),
    )
    if problems:
        row["local_status"] = "qa_failed"
        row["error_message"] = "; ".join(problems)
    else:
        row["local_status"] = "qa_passed"
        row["error_message"] = ""
        row["video_path"] = video["path"]
        row["duration_seconds"] = probe.get("duration_seconds")
        row["width"] = probe.get("width")
        row["height"] = probe.get("height")
        row["checksum_sha256"] = probe.get("checksum_sha256", "")
    row["facts_checked_at"] = utc_now(now)
    row["generation_finished_at"] = utc_now(now)
    store.upsert_reel(row)
    if finalize:
        store.finish_attempt(
            attempt_id, status=row["local_status"], message=row["error_message"], reel_id=reel_id, now=now
        )
    return _stage(row["local_status"], row["error_message"], reel_id)


def _within_budget(config: ReelConfig, store: ReelStore, estimate: float, now: datetime) -> bool:
    if estimate > config.per_reel_max_usd:
        return False
    local = now.astimezone(config.zone)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day = day_start + timedelta(days=1)
    month_start = day_start.replace(day=1)
    if month_start.month == 12:
        next_month = month_start.replace(year=month_start.year + 1, month=1)
    else:
        next_month = month_start.replace(month=month_start.month + 1)
    if store.spent_between(day_start, next_day) + estimate > config.daily_cost_limit_usd:
        return False
    if store.spent_between(month_start, next_month) + estimate > config.monthly_cost_limit_usd:
        return False
    return True


def _technical_problems(probe: dict) -> list[str]:
    problems = []
    if probe.get("width") != 1080 or probe.get("height") != 1920:
        problems.append("resolution")
    if str(probe.get("video_codec", "")).lower() not in {"h264", "avc1"}:
        problems.append("video codec")
    if not probe.get("has_audio"):
        problems.append("audio missing")
    duration = float(probe.get("duration_seconds") or 0)
    if duration < 3 or duration > 900:
        problems.append("duration")
    audio_duration = probe.get("audio_duration_seconds")
    if audio_duration is not None and abs(float(audio_duration) - duration) > 1.0:
        problems.append("audio does not finish with the picture")
    return problems


def _base_row(config, candidate, reel_id, fingerprint, retry_count, checked, now) -> dict:
    stamp = utc_now(now)
    return {
        "reel_id": reel_id,
        "story_fingerprint": fingerprint,
        "target_page": config.target_page,
        "title": candidate.title,
        "category": candidate.category,
        "affected_audience": "Iranians living in Germany",
        "editorial_angle": "",
        "narration_fa": "",
        "caption_fa": "",
        "storyboard_json": "{}",
        "video_path": "",
        "duration_seconds": None,
        "width": None,
        "height": None,
        "checksum_sha256": None,
        "local_status": "researching",
        "production_delivery_id": None,
        "scheduled_for": None,
        "facts_checked_at": stamp,
        "generation_started_at": stamp,
        "generation_finished_at": None,
        "error_message": "",
        "retry_count": retry_count,
        "created_at": stamp,
        "updated_at": stamp,
    }


def _record_rejected(
    store,
    config,
    candidate,
    reel_id,
    fingerprint,
    retry_count,
    message,
    attempt_id,
    now,
    *,
    finalize: bool = True,
) -> None:
    row = _base_row(config, candidate, reel_id, fingerprint, retry_count, {}, now)
    row["local_status"] = "rejected"
    row["error_message"] = message
    row["generation_finished_at"] = utc_now(now)
    store.upsert_reel(row)
    store.add_error(reel_id=reel_id, attempt_id=attempt_id, stage="select", message=message, retryable=False, now=now)
    if finalize:
        store.finish_attempt(attempt_id, status="rejected", message=message, reel_id=reel_id, now=now)


def _record_failed(
    store,
    config,
    candidate,
    reel_id,
    fingerprint,
    retry_count,
    message,
    attempt_id,
    now,
    *,
    stage: str,
    script: dict | None = None,
    checked: dict | None = None,
    finalize: bool = True,
) -> None:
    """Mark a retryable generation failure (for example missing photographs)."""

    row = _base_row(config, candidate, reel_id, fingerprint, retry_count, checked or {}, now)
    if script:
        row["narration_fa"] = str(script.get("narration") or "")
        row["caption_fa"] = str(script.get("caption") or "")
        row["editorial_angle"] = str(script.get("angle") or "")
        row["storyboard_json"] = str(script.get("storyboard_json") or "{}")
    row["local_status"] = "failed"
    row["error_message"] = message
    row["generation_finished_at"] = utc_now(now)
    store.upsert_reel(row)
    store.add_source(
        reel_id,
        url=candidate.url,
        publisher=candidate.publisher,
        title=candidate.title,
        verified_at=utc_now(now),
        excerpt=str((checked or {}).get("excerpt") or "")[:1000],
    )
    store.add_error(reel_id=reel_id, attempt_id=attempt_id, stage=stage, message=message, retryable=True, now=now)
    if finalize:
        store.finish_attempt(attempt_id, status="failed", message=message, reel_id=reel_id, now=now)
