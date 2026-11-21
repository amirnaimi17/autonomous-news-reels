"""Phase 3 Persian script generation. All AI calls are mocked; no network."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.reels.commands import write_grounded_script
from app.reels.config import ReelConfig
from app.reels.pipeline import Candidate, run_generation
from app.reels.store import ReelStore
from app.core.exceptions import GroundingError
from app.services.llm.openai_script import (
    STORY_PACKAGE_JSON_SCHEMA,
    chat_request,
    complete_chat,
    is_schema_compatibility_error,
)
from app.services.llm.persian_script import (
    build_editorial_brief,
    build_fact_pack,
    claim_grounding_errors,
    generate_persian_story_package,
    pipeline_script_from_package,
    structure_errors,
)


SOURCE_URL = "https://example.com/kindergeld-2026"


def _licensed_photos(tmp_path: Path, count: int = 4) -> list[dict]:
    import subprocess

    assets = []
    for index in range(count):
        path = tmp_path / f"script-photo-{index}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x336699:s=800x600:d=0.1",
                "-frames:v",
                "1",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
        assets.append(
            {
                "path": str(path),
                "source_url": f"https://example.org/script/{index}",
                "author": f"Author{index}",
                "license_name": "CC BY 2.0",
                "license_url": "https://creativecommons.org/licenses/by/2.0/",
                "kind": "licensed-photo",
                "role": "scene",
            }
        )
    return assets


def _candidate(now: datetime) -> Candidate:
    return Candidate(
        title="Kindergeld rises to 259 euro in 2026",
        summary=(
            "The federal government confirmed Kindergeld rises to 259 euro per child from January 2026. "
            "Families living in Germany keep the monthly payment."
        ),
        url=SOURCE_URL,
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )


def _config(tmp_path: Path) -> ReelConfig:
    return ReelConfig(
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
        editorial_min_score=0.55,
        editorial_audiences_file=tmp_path / "editorial_audiences.json",
    )


def _mock_package(fact_pack: dict) -> dict:
    url = fact_pack["sources"][0]["url"]
    return {
        "schema_version": "pilot-1",
        "event_id": fact_pack["event_id"],
        "language": "fa-IR",
        "audience": "Iranians living in Germany",
        "headline": "کمک‌هزینه فرزند از ژانویه ۲۰۲۶ به ۲۵۹ یورو می‌رسد",
        "source_urls": [url],
        "claims": [
            {
                "text": "Kindergeld rises to 259 euro per child from January 2026.",
                "source_urls": [url],
            },
            {
                "text": "Families living in Germany keep the monthly payment.",
                "source_urls": [url],
            },
        ],
        "duration_seconds": 40,
        "duration_policy": "completeness",
        "scenes": [
            {
                "number": 1,
                "duration_seconds": 8,
                "narration": "خبر برای خانواده‌های مقیم آلمان: کمک‌هزینه فرزند تغییر می‌کند.",
                "on_screen_text": "خبر خانواده در آلمان",
                "visual_prompt": (
                    "Exterior of a German federal ministry building in Berlin, "
                    "daytime documentary photograph"
                ),
            },
            {
                "number": 2,
                "duration_seconds": 12,
                "narration": "به گزارش بوندس‌رگیرونگ، از ژانویه 2026 این مبلغ به 259 یورو برای هر کودک می‌رسد.",
                "on_screen_text": "از ژانویه ۲۰۲۶\n۲۵۹ یورو",
                "visual_prompt": (
                    "Close-up of euro banknotes and coins on a wooden table, "
                    "documentary photograph suitable for Commons search"
                ),
            },
            {
                "number": 3,
                "duration_seconds": 10,
                "narration": "همان منبع نوشته خانواده‌های ساکن آلمان پرداخت ماهانه را حفظ می‌کنند.",
                "on_screen_text": "پرداخت ماهانه حفظ می‌شود",
                "visual_prompt": (
                    "Family apartment mailbox and letters in a German residential hallway, "
                    "real photograph"
                ),
            },
            {
                "number": 4,
                "duration_seconds": 10,
                "narration": "این گزارش فقط همان ارقام تأییدشده را می‌گوید و رقم تازه‌ای اضافه نمی‌کند.",
                "on_screen_text": "فقط ارقام تأییدشده",
                "visual_prompt": (
                    "Printed German government benefits brochure on a desk next to a pen, "
                    "documentary photograph"
                ),
            },
        ],
        "disclaimers": ["Photographs are illustrative licensed stills, not event footage."],
    }


def test_fact_pack_and_editorial_match_pilot_contracts() -> None:
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(now)
    fact_pack = build_fact_pack(
        title=candidate.title,
        summary=candidate.summary,
        url=candidate.url,
        publisher=candidate.publisher,
        published_at=candidate.published_at,
        excerpt=candidate.title,
    )
    editorial = build_editorial_brief(fact_pack, title=candidate.title, summary=candidate.summary)
    assert fact_pack["status"] == "READY"
    assert fact_pack["sources"][0]["url"] == SOURCE_URL
    assert editorial["decision"] == "APPROVE"
    assert editorial["audience_relevance"]["evidence_urls"] == [SOURCE_URL]


def test_mocked_openai_transport_builds_grounded_pipeline_script(tmp_path: Path) -> None:
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(now)
    config = _config(tmp_path)
    checked = {"ok": True, "excerpt": candidate.summary}
    calls: list[dict] = []

    def transport(spec: dict, api_key: str) -> bytes:
        assert api_key == "unit-test-key"
        assert "Authorization" not in spec
        assert spec["url"] == "https://api.openai.com/v1/chat/completions"
        calls.append(spec)
        fact_pack = build_fact_pack(
            title=candidate.title,
            summary=candidate.summary,
            url=candidate.url,
            publisher=candidate.publisher,
            published_at=candidate.published_at,
            excerpt=candidate.summary,
        )
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_mock_package(fact_pack), ensure_ascii=False),
                    }
                }
            ]
        }
        return json.dumps(body).encode("utf-8")

    def complete(prompt: str, context: dict) -> dict:
        assert "FACT_PACK" in prompt
        return complete_chat(
            prompt,
            context,
            api_key="unit-test-key",
            model="gpt-4o-mini",
            transport=transport,
        )

    result = write_grounded_script(
        candidate,
        checked,
        paid_generation=False,
        complete=complete,
        config=config,
    )
    assert result["status"] == "ready"
    assert "259" in result["narration"]
    assert Path(result["story_package_path"]).is_file()
    assert (config.script_output_dir / result["fact_pack"]["event_id"] / "fact_pack.json").is_file()
    assert len(calls) == 1
    package = result["story_package"]
    assert claim_grounding_errors(package, result["fact_pack"]) == []


def test_ungrounded_figures_are_rejected() -> None:
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(now)
    fact_pack = build_fact_pack(
        title=candidate.title,
        summary=candidate.summary,
        url=candidate.url,
        publisher=candidate.publisher,
        published_at=candidate.published_at,
    )
    editorial = build_editorial_brief(fact_pack, title=candidate.title, summary=candidate.summary)
    bad = _mock_package(fact_pack)
    bad["scenes"][1]["narration"] = "مبلغ به 999 یورو می‌رسد."
    bad["claims"][0]["text"] = "Kindergeld rises to 999 euro."
    calls = {"n": 0}

    def complete(prompt: str, context: dict) -> dict:
        del prompt, context
        calls["n"] += 1
        return bad

    with pytest.raises(GroundingError) as raised:
        generate_persian_story_package(fact_pack, editorial, complete=complete)
    assert calls["n"] == 2
    assert "figures" in str(raised.value).lower() or "999" in str(raised.value)
    assert "after correction" in str(raised.value).lower()


def test_pipeline_stores_script_then_blocks_voice_without_paid_generation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(now)

    def complete(prompt: str, context: dict) -> dict:
        del prompt
        return _mock_package(context["fact_pack"])

    def write_script(candidate, checked, paid_generation):
        return write_grounded_script(
            candidate,
            checked,
            paid_generation=paid_generation,
            complete=complete,
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
        find_assets=lambda candidate, script: _licensed_photos(tmp_path),
        narrate=lambda text, voice_id: (_ for _ in ()).throw(AssertionError("ElevenLabs must not run")),
        render_video=lambda script, assets, audio: (_ for _ in ()).throw(AssertionError("video must not run")),
        probe_video=lambda path: (_ for _ in ()).throw(AssertionError("probe must not run")),
    )
    assert result.status == "blocked_paid"
    reel = store.get(result.reel_id)
    assert reel is not None
    assert "259" in reel["narration_fa"]
    assert reel["caption_fa"]
    assert json.loads(reel["storyboard_json"])


def test_default_off_provider_still_blocks_without_paid_generation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    config = ReelConfig(**{**config.__dict__, "script_provider": "off"})
    candidate = _candidate(datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc))
    result = write_grounded_script(
        candidate,
        {"ok": True, "excerpt": candidate.summary},
        paid_generation=False,
        config=config,
    )
    assert result["status"] == "blocked_paid"


def test_chat_request_shape_excludes_secrets() -> None:
    spec = chat_request("return json")
    assert spec["url"] == "https://api.openai.com/v1/chat/completions"
    assert "api_key" not in spec
    assert "Authorization" not in spec
    fmt = spec["body"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["schema"] == STORY_PACKAGE_JSON_SCHEMA
    assert STORY_PACKAGE_JSON_SCHEMA["properties"]["scenes"]["type"] == "array"
    fallback = chat_request("return json", use_json_schema=False)
    assert fallback["body"]["response_format"] == {"type": "json_object"}


def test_schema_compatibility_error_detection() -> None:
    assert is_schema_compatibility_error(
        400,
        '{"error":{"message":"Invalid schema for response_format json_schema"}}',
    )
    assert is_schema_compatibility_error(
        400,
        "response_format type json_schema is not supported with this model",
    )
    assert not is_schema_compatibility_error(400, '{"error":{"message":"Invalid API key"}}')
    assert not is_schema_compatibility_error(400, "rate limit exceeded for requests")
    assert not is_schema_compatibility_error(500, "response_format json_schema boom")
    assert not is_schema_compatibility_error(404, "model not found")


def test_complete_chat_downgrades_only_on_schema_compat_errors() -> None:
    calls: list[dict] = []

    def transport_unrelated(spec: dict, api_key: str) -> bytes:
        calls.append(spec)
        import urllib.error

        raise urllib.error.HTTPError(
            spec["url"],
            400,
            "Bad Request",
            hdrs=None,  # type: ignore[arg-type]
            fp=__import__("io").BytesIO(b'{"error":{"message":"Invalid API key provided"}}'),
        )

    with pytest.raises(GroundingError, match="HTTP 400"):
        complete_chat("return json", api_key="unit-test-key", transport=transport_unrelated)
    assert len(calls) == 1
    assert calls[0]["body"]["response_format"]["type"] == "json_schema"

    calls.clear()

    def transport_schema_then_ok(spec: dict, api_key: str) -> bytes:
        calls.append(spec)
        fmt = spec["body"]["response_format"]
        if fmt.get("type") == "json_schema":
            import urllib.error

            raise urllib.error.HTTPError(
                spec["url"],
                400,
                "Bad Request",
                hdrs=None,  # type: ignore[arg-type]
                fp=__import__("io").BytesIO(
                    b'{"error":{"message":"Invalid schema for response_format \'json_schema\'"}}'
                ),
            )
        body = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "schema_version": "pilot-1",
                                "event_id": "x",
                                "language": "fa-IR",
                                "audience": "test",
                                "headline": "عنوان",
                                "source_urls": ["https://example.com/x"],
                                "claims": [{"text": "x", "source_urls": ["https://example.com/x"]}],
                                "duration_seconds": 8,
                                "duration_policy": "",
                                "scenes": [
                                    {
                                        "number": 1,
                                        "duration_seconds": 8,
                                        "narration": "متن",
                                        "on_screen_text": "متن",
                                        "visual_prompt": "Berlin ministry exterior photograph",
                                    }
                                ]
                                * 3,
                                "disclaimers": [],
                            }
                        )
                    }
                }
            ]
        }
        return json.dumps(body).encode("utf-8")

    result = complete_chat("return json", api_key="unit-test-key", transport=transport_schema_then_ok)
    assert result["event_id"] == "x"
    assert len(calls) == 2
    assert calls[0]["body"]["response_format"]["type"] == "json_schema"
    assert calls[1]["body"]["response_format"]["type"] == "json_object"


def test_structure_errors_missing_scenes() -> None:
    package = _mock_package(
        build_fact_pack(
            title="t",
            summary="Kindergeld rises to 259 euro.",
            url=SOURCE_URL,
            publisher="Bundesregierung",
            published_at=datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
        )
    )
    del package["scenes"]
    errors = structure_errors(package)
    assert any("missing" in item for item in errors)


def test_structure_errors_scenes_as_object() -> None:
    package = _mock_package(
        build_fact_pack(
            title="t",
            summary="Kindergeld rises to 259 euro.",
            url=SOURCE_URL,
            publisher="Bundesregierung",
            published_at=datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
        )
    )
    package["scenes"] = {"1": package["scenes"][0], "2": package["scenes"][1]}
    errors = structure_errors(package)
    assert any("must be a list" in item for item in errors)


def test_valid_story_package_accepted() -> None:
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(now)
    fact_pack = build_fact_pack(
        title=candidate.title,
        summary=candidate.summary,
        url=candidate.url,
        publisher=candidate.publisher,
        published_at=candidate.published_at,
    )
    editorial = build_editorial_brief(fact_pack, title=candidate.title, summary=candidate.summary)
    calls = {"n": 0}

    def complete(prompt: str, context: dict) -> dict:
        del prompt, context
        calls["n"] += 1
        return _mock_package(fact_pack)

    package = generate_persian_story_package(fact_pack, editorial, complete=complete)
    assert calls["n"] == 1
    assert isinstance(package["scenes"], list)
    assert package["_openai_script_calls"] == 1
    assert structure_errors(package) == []
    assert claim_grounding_errors(package, fact_pack) == []


def test_correction_succeeds_after_one_invalid_response() -> None:
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(now)
    fact_pack = build_fact_pack(
        title=candidate.title,
        summary=candidate.summary,
        url=candidate.url,
        publisher=candidate.publisher,
        published_at=candidate.published_at,
    )
    editorial = build_editorial_brief(fact_pack, title=candidate.title, summary=candidate.summary)
    good = _mock_package(fact_pack)
    bad = dict(good)
    bad["scenes"] = {str(i + 1): scene for i, scene in enumerate(good["scenes"])}
    responses = [bad, good]
    prompts: list[str] = []

    def complete(prompt: str, context: dict) -> dict:
        prompts.append(prompt)
        assert context.get("attempt") in {1, 2}
        return responses.pop(0)

    package = generate_persian_story_package(fact_pack, editorial, complete=complete)
    assert isinstance(package["scenes"], list)
    assert package["_openai_script_calls"] == 2
    assert "VALIDATION_ERRORS" in prompts[1]
    assert "must be a list" in prompts[1]


def test_correction_fails_after_second_invalid_response() -> None:
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(now)
    fact_pack = build_fact_pack(
        title=candidate.title,
        summary=candidate.summary,
        url=candidate.url,
        publisher=candidate.publisher,
        published_at=candidate.published_at,
    )
    editorial = build_editorial_brief(fact_pack, title=candidate.title, summary=candidate.summary)
    bad = _mock_package(fact_pack)
    del bad["scenes"]
    calls = {"n": 0}

    def complete(prompt: str, context: dict) -> dict:
        del prompt, context
        calls["n"] += 1
        return bad

    with pytest.raises(GroundingError) as raised:
        generate_persian_story_package(fact_pack, editorial, complete=complete)
    assert calls["n"] == 2
    assert "after correction" in str(raised.value).lower()
    assert "scenes" in str(raised.value).lower()


def test_invalid_package_never_reaches_voice_or_video(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(now)

    def complete(prompt: str, context: dict) -> dict:
        del prompt
        package = _mock_package(context["fact_pack"])
        del package["scenes"]
        return package

    def write_script(candidate, checked, paid_generation):
        return write_grounded_script(
            candidate,
            checked,
            paid_generation=paid_generation,
            complete=complete,
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
        find_assets=lambda candidate, script: (_ for _ in ()).throw(
            AssertionError("photo retrieval must not run on invalid script")
        ),
        narrate=lambda text, voice_id: (_ for _ in ()).throw(AssertionError("ElevenLabs must not run")),
        render_video=lambda script, assets, audio: (_ for _ in ()).throw(
            AssertionError("Remotion must not run")
        ),
        probe_video=lambda path: (_ for _ in ()).throw(AssertionError("probe must not run")),
    )
    assert result.status == "rejected"
    assert "scenes" in (result.message or "").lower()


def test_pipeline_script_estimate_uses_character_rate() -> None:
    package = {
        "headline": "عنوان",
        "scenes": [
            {
                "number": 1,
                "duration_seconds": 8,
                "narration": "سلام",
                "on_screen_text": "سلام",
                "visual_prompt": "Berlin city hall exterior documentary photograph",
            }
        ],
    }
    result = pipeline_script_from_package(package)
    assert result["status"] == "ready"
    assert result["voice_estimate_usd"] == round(len("سلام") * 0.08 / 1000, 6)
