"""Narration quality reviewer. All LLM calls are mocked; no paid network."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.exceptions import GroundingError
from app.reels.commands import write_grounded_script
from app.reels.config import ReelConfig
from app.reels.pipeline import Candidate, run_generation
from app.reels.store import ReelStore
from app.services.llm.narration_review import (
    NARRATION_REVIEW_JSON_SCHEMA,
    NarrationReviewThresholds,
    decide_from_scores,
    glossary_factual_errors,
    load_german_term_glossary,
    review_and_refine_story_package,
    spoken_length_errors,
)
from app.services.llm.openai_script import STORY_PACKAGE_JSON_SCHEMA
from app.services.llm.persian_script import build_editorial_brief, build_fact_pack
from app.services.news.editorial_rank import EDITORIAL_RANKING_JSON_SCHEMA


SOURCE_URL = "https://example.com/kindergeld-narration"


def _config(tmp_path: Path, **overrides) -> ReelConfig:
    base = dict(
        database_path=tmp_path / "reels.sqlite3",
        outbox_dir=tmp_path / "outbox",
        lock_path=tmp_path / "reels.lock",
        log_path=tmp_path / "generate.log",
        timezone="Europe/Berlin",
        target_page="almanyar",
        generation_hours=(7, 11, 15, 19),
        slot_grace_minutes=20,
        news_window_hours=36,
        freshness_hours=18,
        paid_generation=False,
        per_reel_max_usd=0.50,
        daily_cost_limit_usd=2.0,
        monthly_cost_limit_usd=60.0,
        ingest_url="",
        ingest_token="",
        python_executable="/usr/bin/python3",
        working_directory=tmp_path,
        sources_file=tmp_path / "sources.json",
        voice_id="PEdcOLzbXYhL8IKOswXB",
        max_attempts=3,
        script_provider="openai",
        script_model="gpt-4o-mini",
        script_output_dir=tmp_path / "scripts",
        elevenlabs_approved=False,
        audio_output_dir=tmp_path / "audio",
        editorial_rank_provider="off",
        editorial_rank_approved=False,
        editorial_audience_id="iranians_in_germany",
        editorial_min_score=None,
        editorial_audiences_file=tmp_path / "editorial_audiences.json",
        narration_review_provider="openai",
        narration_review_enabled=True,
        narration_review_min_score=80.0,
        narration_review_hook_min_score=80.0,
        narration_review_curiosity_min_score=75.0,
        narration_review_max_rewrites=1,
        narration_glossary_file=Path("config/german_term_glossary.json"),
    )
    base.update(overrides)
    return ReelConfig(**base)


def _fact_and_editorial():
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    fact_pack = build_fact_pack(
        title="Kindergeld rises to 259 euro in 2026",
        summary=(
            "The federal government confirmed Kindergeld rises to 259 euro per child from January 2026. "
            "Families living in Germany keep the monthly payment."
        ),
        url=SOURCE_URL,
        publisher="Bundesregierung",
        published_at=now,
        excerpt="Kindergeld rises to 259 euro per child from January 2026.",
    )
    editorial = build_editorial_brief(
        fact_pack,
        title="Kindergeld rises to 259 euro in 2026",
        summary=fact_pack["event_summary"],
    )
    return fact_pack, editorial


def _long_scenes(url: str) -> list[dict]:
    # ~420+ Persian characters → ~35s at measured Aran rate.
    # Keep numerals in ASCII so grounding matches the English fact pack figures.
    lines = [
        "خبر مهم برای خانواده‌های مقیم آلمان: کمک‌هزینه فرزند قرار است تغییر کند و رقمش بالاتر برود.",
        "طبق گزارش رسمی، از ژانویه 2026 مبلغ Kindergeld به 259 یورو برای هر کودک می‌رسد و این رقم در منبع تأیید شده است.",
        "یعنی اگر در آلمان زندگی می‌کنید و این پرداخت را می‌گیرید، مبلغ ماهانه شما بر اساس همان اعلام رسمی به‌روز می‌شود و خانواده همان کمک ماهانه را حفظ می‌کند.",
        "جزئیات بیشتر را از همان منبع رسمی دنبال کنید تا رقم تازه‌ای خارج از گزارش اضافه نشود و برنامه مالی‌تان دقیق بماند برای ماه‌های بعد.",
    ]
    return [
        {
            "number": index + 1,
            "duration_seconds": 10,
            "narration": line,
            "on_screen_text": f"صحنه {index + 1}",
            "visual_prompt": "German family benefits brochure on a desk documentary photograph",
        }
        for index, line in enumerate(lines)
    ]


def _package(fact_pack: dict, *, fruehstart_bad: bool = False, short: bool = False) -> dict:
    url = fact_pack["sources"][0]["url"]
    if short:
        scenes = [
            {
                "number": i + 1,
                "duration_seconds": 5,
                "narration": "خبر کوتاه است.",
                "on_screen_text": str(i + 1),
                "visual_prompt": "Berlin government building exterior documentary photograph",
            }
            for i in range(4)
        ]
    else:
        scenes = _long_scenes(url)
        if fruehstart_bad:
            scenes[1]["narration"] = (
                "این طرح مثل بازنشستگی زودهنگام عمل می‌کند و عدد 259 یورو هم در متن آمده است."
            )
    return {
        "schema_version": "pilot-1",
        "event_id": fact_pack["event_id"],
        "language": "fa-IR",
        "audience": "Iranians living in Germany",
        "headline": "کمک‌هزینه فرزند از ژانویه ۲۰۲۶",
        "source_urls": [url],
        "claims": [
            {"text": "Kindergeld rises to 259 euro per child from January 2026.", "source_urls": [url]},
            {"text": "Families living in Germany keep the monthly payment.", "source_urls": [url]},
        ],
        "duration_seconds": 40,
        "duration_policy": "completeness",
        "scenes": scenes,
        "disclaimers": [],
    }


def _scores(**overrides) -> dict:
    base = {
        "hook_strength": 88,
        "listener_involvement": 90,
        "curiosity_and_retention": 86,
        "storytelling_flow": 85,
        "natural_spoken_persian": 92,
        "clarity": 90,
        "practical_usefulness": 84,
        "ending_quality": 83,
    }
    base.update(overrides)
    return base


def _evidence() -> dict:
    return {key: f"evidence text for {key} with example sentence" for key in _scores()}


def _review_payload(**score_overrides) -> dict:
    scores = _scores(**score_overrides)
    return {
        "approved": True,
        "overall_score": 99,
        "scores": scores,
        "score_evidence": _evidence(),
        "factual_errors": [],
        "editorial_issues": [],
        "weakest_sentence": "جزئیات بیشتر را از همان منبع رسمی دنبال کنید.",
        "drop_off_risk": {
            "scene": 4,
            "reason": "Slightly generic close",
            "suggested_replacement": "رقم ۲۵۹ یورو را در برنامه ماهانه‌تان وارد کنید.",
        },
        "rewrite_required": False,
        "reason": "strong engagement",
    }


def test_review_schema_is_independent_from_other_schemas() -> None:
    assert "scores" in NARRATION_REVIEW_JSON_SCHEMA["properties"]
    assert "scenes" not in NARRATION_REVIEW_JSON_SCHEMA["properties"]
    assert "rankings" not in NARRATION_REVIEW_JSON_SCHEMA["properties"]
    assert "scores" not in STORY_PACKAGE_JSON_SCHEMA["properties"]
    assert "scores" not in EDITORIAL_RANKING_JSON_SCHEMA["properties"]


def test_strong_hook_gets_approved() -> None:
    fact_pack, editorial = _fact_and_editorial()
    package = _package(fact_pack)

    def review_complete(prompt, context=None, **kwargs):
        return _review_payload()

    result = review_and_refine_story_package(
        fact_pack=fact_pack,
        editorial=editorial,
        package=package,
        title="Kindergeld",
        source_url=SOURCE_URL,
        review_complete=review_complete,
        rewrite_complete=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no rewrite")),
    )
    assert result.approved is True
    assert result.decision == "APPROVED"
    assert result.openai_calls == 1
    assert result.overall_score >= 80


def test_weak_hook_triggers_rewrite_then_can_pass() -> None:
    fact_pack, editorial = _fact_and_editorial()
    package = _package(fact_pack)
    calls = {"review": 0, "rewrite": 0}

    def review_complete(prompt, context=None, **kwargs):
        calls["review"] += 1
        if calls["review"] == 1:
            return _review_payload(hook_strength=40, curiosity_and_retention=40, listener_involvement=40)
        return _review_payload()

    def rewrite_complete(prompt, context):
        calls["rewrite"] += 1
        assert "REVIEW_FEEDBACK" in prompt or "hook" in prompt.lower() or "REVIEW" in prompt
        return _package(context["fact_pack"])

    result = review_and_refine_story_package(
        fact_pack=fact_pack,
        editorial=editorial,
        package=package,
        title="Kindergeld",
        source_url=SOURCE_URL,
        review_complete=review_complete,
        rewrite_complete=rewrite_complete,
    )
    assert calls["review"] == 2
    assert calls["rewrite"] == 1
    assert result.approved is True
    assert result.rewritten_package is not None


def test_low_curiosity_triggers_rewrite() -> None:
    fact_pack, editorial = _fact_and_editorial()
    package = _package(fact_pack)
    reviews = []

    def review_complete(prompt, context=None, **kwargs):
        reviews.append(1)
        if len(reviews) == 1:
            return _review_payload(curiosity_and_retention=50)
        return _review_payload()

    result = review_and_refine_story_package(
        fact_pack=fact_pack,
        editorial=editorial,
        package=package,
        title="Kindergeld",
        source_url=SOURCE_URL,
        review_complete=review_complete,
        rewrite_complete=lambda prompt, context: _package(context["fact_pack"]),
    )
    assert len(reviews) == 2
    assert result.approved is True


def test_decide_from_scores_blocks_factual_even_with_high_scores() -> None:
    payload = _review_payload()
    payload["factual_errors"] = [{"scene": 1, "claim": "x", "problem": "unsupported"}]
    payload["scores"] = _scores(
        hook_strength=99,
        listener_involvement=99,
        curiosity_and_retention=99,
        storytelling_flow=99,
        natural_spoken_persian=99,
        clarity=99,
        practical_usefulness=99,
        ending_quality=99,
    )
    decided = decide_from_scores(payload, thresholds=NarrationReviewThresholds())
    assert decided["approved"] is False
    assert "factual" in decided["reason"]


def test_misleading_fruehstartrente_translation_is_rejected() -> None:
    glossary = load_german_term_glossary()
    fact_pack, _editorial = _fact_and_editorial()
    package = _package(fact_pack, fruehstart_bad=True)
    errors = glossary_factual_errors(package, glossary)
    assert errors
    assert any("Frühstartrente" in item["problem"] or "misleading" in item["problem"] for item in errors)


def test_spoken_length_errors_for_short_package() -> None:
    fact_pack, _ = _fact_and_editorial()
    package = _package(fact_pack, short=True)
    assert spoken_length_errors(package, min_spoken_seconds=32)


def test_invalid_rewrite_is_rejected() -> None:
    fact_pack, editorial = _fact_and_editorial()
    package = _package(fact_pack)

    def review_complete(prompt, context=None, **kwargs):
        # Always weak so rewrite happens, then second review also fails.
        return _review_payload(hook_strength=30, curiosity_and_retention=30)

    def rewrite_complete(prompt, context):
        return _package(context["fact_pack"])

    result = review_and_refine_story_package(
        fact_pack=fact_pack,
        editorial=editorial,
        package=package,
        title="Kindergeld",
        source_url=SOURCE_URL,
        review_complete=review_complete,
        rewrite_complete=rewrite_complete,
    )
    assert result.approved is False
    assert result.decision == "REJECTED"
    assert result.openai_calls == 3  # review + rewrite + review


def test_max_rewrite_limit_enforced() -> None:
    fact_pack, editorial = _fact_and_editorial()
    package = _package(fact_pack)
    rewrite_calls = {"n": 0}

    def review_complete(prompt, context=None, **kwargs):
        return _review_payload(hook_strength=20, curiosity_and_retention=20)

    def rewrite_complete(prompt, context):
        rewrite_calls["n"] += 1
        return _package(context["fact_pack"])

    result = review_and_refine_story_package(
        fact_pack=fact_pack,
        editorial=editorial,
        package=package,
        title="Kindergeld",
        source_url=SOURCE_URL,
        thresholds=NarrationReviewThresholds(max_rewrites=0),
        review_complete=review_complete,
        rewrite_complete=rewrite_complete,
    )
    assert rewrite_calls["n"] == 0
    assert result.approved is False


def test_review_failure_blocks_photos_voice_and_video(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Kindergeld rises to 259 euro in 2026",
        summary="The federal government confirmed Kindergeld rises to 259 euro per child from January 2026.",
        url=SOURCE_URL,
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )

    def script_complete(prompt, context):
        return _package(context["fact_pack"])

    def review_complete(prompt, context=None, **kwargs):
        return _review_payload(hook_strength=10, curiosity_and_retention=10, listener_involvement=10)

    def write_script(candidate, checked, paid_generation):
        return write_grounded_script(
            candidate,
            checked,
            paid_generation=paid_generation,
            complete=script_complete,
            review_complete=review_complete,
            rewrite_complete=lambda prompt, context: _package(context["fact_pack"]),
            config=config,
        )

    result = run_generation(
        config,
        store,
        now=now,
        scheduled=False,
        candidates=[candidate],
        verify_source=lambda item: {"ok": True, "excerpt": item.summary},
        write_script=write_script,
        find_assets=lambda *a, **k: (_ for _ in ()).throw(AssertionError("photos blocked")),
        narrate=lambda *a, **k: (_ for _ in ()).throw(AssertionError("ElevenLabs blocked")),
        render_video=lambda *a, **k: (_ for _ in ()).throw(AssertionError("Remotion blocked")),
        probe_video=lambda *a, **k: (_ for _ in ()).throw(AssertionError("probe blocked")),
    )
    assert result.status == "rejected"
    assert "narration quality" in (result.message or "").lower()


def test_manual_and_scheduled_share_write_grounded_script_review(tmp_path: Path) -> None:
    """Both CLI paths use write_grounded_script; review runs when enabled."""

    config = _config(tmp_path)
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Kindergeld rises to 259 euro in 2026",
        summary="The federal government confirmed Kindergeld rises to 259 euro per child from January 2026. Families living in Germany keep the monthly payment.",
        url=SOURCE_URL,
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )
    reviews = {"n": 0}

    def review_complete(prompt, context=None, **kwargs):
        reviews["n"] += 1
        return _review_payload()

    result = write_grounded_script(
        candidate,
        {"ok": True, "excerpt": candidate.summary},
        paid_generation=False,
        complete=lambda prompt, context: _package(context["fact_pack"]),
        review_complete=review_complete,
        config=config,
    )
    assert result["status"] == "ready"
    assert reviews["n"] == 1
    assert result["narration_review"]["decision"] == "APPROVED"
    # Scheduled uses the same function; enabling config is enough.
    assert config.narration_review_enabled is True


def test_unsupported_claim_forces_rewrite_then_clean_package_can_pass() -> None:
    fact_pack, editorial = _fact_and_editorial()
    package = _package(fact_pack)
    package["scenes"][1]["narration"] = (
        "طبق گزارش رسمی، مبلغ به ۹۹۹ یورو می‌رسد و این رقم در منبع تأیید شده است و برای هر کودک پرداخت می‌شود."
    )
    package["claims"][0]["text"] = "Kindergeld rises to 999 euro."
    passes = {"n": 0}

    def review_complete(prompt, context=None, **kwargs):
        passes["n"] += 1
        return _review_payload()

    result = review_and_refine_story_package(
        fact_pack=fact_pack,
        editorial=editorial,
        package=package,
        title="Kindergeld",
        source_url=SOURCE_URL,
        review_complete=review_complete,
        rewrite_complete=lambda prompt, context: _package(context["fact_pack"]),
    )
    assert passes["n"] == 2
    assert result.approved is True
    assert "999" not in " ".join(
        str(scene.get("narration")) for scene in result.package["scenes"]
    )


def test_review_costs_respect_budget() -> None:
    fact_pack, editorial = _fact_and_editorial()
    package = _package(fact_pack)

    with pytest.raises(GroundingError, match="budget"):
        review_and_refine_story_package(
            fact_pack=fact_pack,
            editorial=editorial,
            package=package,
            title="Kindergeld",
            source_url=SOURCE_URL,
            review_complete=lambda *a, **k: _review_payload(),
            rewrite_complete=lambda *a, **k: _package(fact_pack),
            budget_usd=0.0000001,
        )
