"""Phase 7 live pilot gates. No paid network calls in these tests."""

from __future__ import annotations

import json
from pathlib import Path

from app.reels.live_pilot import estimate_live_reel_cost, run_live_persian_reel
from app.reels.pilot import run_persian_reel_pilot


def test_estimate_live_reel_cost_under_cap() -> None:
    estimate = estimate_live_reel_cost(narration_chars=520)
    assert estimate.status == "estimated"
    assert estimate.total_usd is not None
    assert estimate.total_usd < 0.50
    assert estimate.under_cap is True
    assert estimate.detail["elevenlabs"]["voice_id"] == "PEdcOLzbXYhL8IKOswXB"
    assert estimate.detail["elevenlabs"]["usd"] == round(520 * 0.00008, 6)


def test_live_pilot_blocks_without_approval(tmp_path: Path) -> None:
    pack = {
        "event_id": "test-live",
        "status": "READY",
        "retrieved_at": "2026-11-21T00:00:00+00:00",
        "event_summary": "Test",
        "sources": [{"publisher": "Test", "url": "https://example.org/a", "published_at": None}],
        "verified_facts": [{"text": "Test fact 10 euro.", "source_urls": ["https://example.org/a"]}],
        "uncertainties": [],
        "duplicate_risk": "none",
    }
    editorial = {
        "event_id": "test-live",
        "decision": "APPROVE",
        "rationale": "test",
        "limitations": [],
        "audience_relevance": {
            "affected_audience": "Iranians living in Germany",
            "practical_relevance": "test",
            "evidence_urls": ["https://example.org/a"],
            "publication_reason": "test",
        },
    }
    fact_path = tmp_path / "fact_pack.json"
    ed_path = tmp_path / "editorial_review.json"
    fact_path.write_text(json.dumps(pack), encoding="utf-8")
    ed_path.write_text(json.dumps(editorial), encoding="utf-8")
    result = run_live_persian_reel(
        fact_pack=fact_path,
        editorial_review=ed_path,
        out_dir=tmp_path / "out",
        approve_paid=False,
        planned_narration_chars=400,
    )
    assert result["status"] == "awaiting_approval"
    assert result.get("paid_api_calls") is not True
    assert (tmp_path / "out" / "cost_estimate.json").is_file()
    estimate = json.loads((tmp_path / "out" / "cost_estimate.json").read_text(encoding="utf-8"))
    assert estimate["under_cap"] is True


def test_require_live_voice_refuses_silent_fixture(tmp_path: Path) -> None:
    story = {
        "schema_version": "pilot-1",
        "event_id": "silent-guard",
        "language": "fa-IR",
        "audience": "test",
        "headline": "آزمون",
        "source_urls": ["https://example.org/x"],
        "claims": [{"text": "x", "source_urls": ["https://example.org/x"]}],
        "duration_seconds": 4,
        "scenes": [
            {
                "number": 1,
                "duration_seconds": 4,
                "narration": "این فقط یک آزمون است.",
                "on_screen_text": "آزمون",
                "visual_prompt": "graphic",
            }
        ],
        "disclaimers": [],
    }
    result = run_persian_reel_pilot(
        out_dir=tmp_path / "pilot",
        story_package=story,
        require_live_voice=True,
        skip_render=True,
        overwrite=True,
    )
    assert result.status == "failed"
    assert "silent" in result.message.lower() or "live voice" in result.message.lower()
