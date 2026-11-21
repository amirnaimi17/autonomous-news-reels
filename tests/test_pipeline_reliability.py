"""Pipeline reliability: numeral grounding, article fallback, and one E2E reel."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.reels.config import ReelConfig
from app.reels.pipeline import Candidate, run_generation
from app.reels.render import make_silent_mp3
from app.reels.store import ReelStore
from app.services.grounding import numbers_missing_from_source
from app.services.llm.persian_script import (
    build_editorial_brief,
    build_fact_pack,
    claim_grounding_errors,
    generate_persian_story_package,
    pipeline_script_from_package,
)


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
        paid_generation=True,
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
        elevenlabs_approved=True,
        audio_output_dir=tmp_path / "audio",
        editorial_rank_provider="off",
        editorial_rank_approved=False,
        editorial_audience_id="iranians_in_germany",
        editorial_min_score=0.55,
        editorial_audiences_file=tmp_path / "editorial_audiences.json",
    )
    base.update(overrides)
    return ReelConfig(**base)


def _jpeg(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
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
    return path


def _candidate(now: datetime, *, title: str, url: str, summary: str) -> Candidate:
    return Candidate(
        title=title,
        summary=summary,
        url=url,
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )


def _story_package(fact_pack: dict, *, amount_fa: str = "۲۵۹") -> dict:
    url = fact_pack["sources"][0]["url"]
    return {
        "schema_version": "pilot-1",
        "event_id": fact_pack["event_id"],
        "language": "fa-IR",
        "audience": "Iranians living in Germany",
        "headline": f"کمک‌هزینه فرزند به {amount_fa} یورو می‌رسد",
        "source_urls": [url],
        "claims": [
            {
                "text": "Kindergeld rises to 259 euro per child from January 2026.",
                "source_urls": [url],
            }
        ],
        "duration_seconds": 40,
        "duration_policy": "completeness",
        "scenes": [
            {
                "number": i + 1,
                "duration_seconds": 10,
                "narration": narration,
                "on_screen_text": f"صحنه {i + 1}",
                "visual_prompt": visual,
            }
            for i, (narration, visual) in enumerate(
                [
                    (
                        "خبر برای خانواده‌های مقیم آلمان: کمک‌هزینه فرزند تغییر می‌کند.",
                        "German federal ministry building Berlin exterior photograph",
                    ),
                    (
                        f"به گزارش منبع رسمی، مبلغ ماهانه به {amount_fa} یورو برای هر کودک می‌رسد.",
                        "Euro banknotes and coins on a table documentary photograph",
                    ),
                    (
                        "خانواده‌های ساکن آلمان پرداخت ماهانه را حفظ می‌کنند.",
                        "Berlin residential street everyday life photograph",
                    ),
                    (
                        "این گزارش فقط همان ارقام تأییدشده را می‌گوید.",
                        "German benefits brochure on desk documentary photograph",
                    ),
                ]
            )
        ],
        "disclaimers": [],
    }


def test_fact_pack_prefers_figure_bearing_excerpt_sentences() -> None:
    pack = build_fact_pack(
        title="Kindergeld update",
        summary="Families in Germany keep monthly Kindergeld.",
        url="https://example.com/kindergeld",
        publisher="Bundesregierung",
        published_at=datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc),
        excerpt=(
            "The ministry published a long introduction without a figure. "
            "Kindergeld rises to 259 euro per child from January 2026. "
            "Another sentence without numbers follows for context. "
            "Households receive the payment each month."
        ),
    )
    texts = [item["text"] for item in pack["verified_facts"]]
    assert any("259" in text for text in texts)
    # Figure-bearing excerpt sentence is retained among verified facts.
    assert any(text.startswith("Kindergeld rises to 259") for text in texts)


def test_article_fallback_tries_next_ranked_story(tmp_path: Path) -> None:
    config = _config(tmp_path, paid_generation=False)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    first = _candidate(
        now,
        title="Kindergeld rises to 259 euro",
        url="https://example.com/kindergeld-bad",
        summary="Families in Germany keep Kindergeld at 259 euro.",
    )
    second = _candidate(
        now,
        title="Mindestlohn rises in Germany",
        url="https://example.com/mindestlohn-ok",
        summary="The federal minimum wage increase affects workers in Germany.",
    )
    photos = [_jpeg(tmp_path / f"photo-{i}.jpg") for i in range(4)]
    script_calls: list[str] = []

    def write_script(candidate, checked, paid_generation):
        script_calls.append(candidate.url)
        if "kindergeld-bad" in candidate.url:
            return {"status": "rejected", "message": "story package invalid: unsupported figure"}
        return {
            "status": "ready",
            "narration": "خبر کوتاه درباره حداقل دستمزد.",
            "caption": "حداقل دستمزد",
            "angle": "Mindestlohn",
            "storyboard_json": json.dumps(
                [
                    {
                        "number": i + 1,
                        "duration_seconds": 3,
                        "narration": f"صحنه {i + 1}",
                        "on_screen_text": str(i + 1),
                        "visual_prompt": "German workplace photograph",
                    }
                    for i in range(4)
                ],
                ensure_ascii=False,
            ),
            "voice_estimate_usd": 0.01,
            "story_package": {"scenes": [{"number": i + 1} for i in range(4)]},
        }

    result = run_generation(
        config,
        store,
        now=now,
        scheduled=False,
        candidates=[first, second],
        verify_source=lambda item: {"ok": True, "excerpt": item.summary},
        write_script=write_script,
        find_assets=lambda candidate, script: [
            {
                "path": str(photos[i]),
                "source_url": f"https://example.org/{i}",
                "author": "",
                "license_name": "",
                "license_url": "",
                "kind": "licensed-photo",
                "role": "scene",
            }
            for i in range(4)
        ],
        narrate=lambda *a, **k: (_ for _ in ()).throw(AssertionError("voice must not run")),
        render_video=lambda *a, **k: (_ for _ in ()).throw(AssertionError("render must not run")),
        probe_video=lambda path: {},
    )
    assert script_calls == [
        "https://example.com/kindergeld-bad",
        "https://example.com/mindestlohn-ok",
    ]
    assert result.status == "blocked_paid"
    assert len(result.detail.get("article_attempts") or []) == 2
    assert result.detail["article_attempts"][0]["status"] == "rejected"
    assert result.detail["article_attempts"][1]["status"] == "blocked_paid"
    assert result.detail["article_attempts"][1]["url"] == second.url


def test_end_to_end_reliable_reel_with_persian_numerals(tmp_path: Path, monkeypatch) -> None:
    """One mocked end-to-end path: story → grounding → photos → silent voice → MP4."""

    import app.reels.render as render_mod

    public = tmp_path / "public"
    public.mkdir()
    monkeypatch.setattr(render_mod, "PUBLIC", public)

    config = _config(tmp_path, paid_generation=True)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(
        now,
        title="Kindergeld rises to 259 euro",
        url="https://example.com/kindergeld-e2e",
        summary="Families in Germany keep Kindergeld. The monthly amount is 259 euro from January 2026.",
    )
    excerpt = (
        "The federal government confirmed Kindergeld rises to 259 euro per child "
        "from January 2026 for households in Germany."
    )
    fact_pack = build_fact_pack(
        title=candidate.title,
        summary=candidate.summary,
        url=candidate.url,
        publisher=candidate.publisher,
        published_at=candidate.published_at,
        excerpt=excerpt,
    )
    editorial = build_editorial_brief(fact_pack, title=candidate.title, summary=candidate.summary)
    package = _story_package(fact_pack, amount_fa="۲۵۹")
    assert numbers_missing_from_source(
        " ".join(scene["narration"] for scene in package["scenes"]),
        "\n".join(item["text"] for item in fact_pack["verified_facts"]),
    ) == []
    assert claim_grounding_errors(package, fact_pack) == []

    photos = [_jpeg(tmp_path / "assets" / f"scene-{i:02d}.jpg") for i in range(1, 5)]
    audio_path = tmp_path / "audio" / "narration.mp3"
    make_silent_mp3(audio_path, seconds=8.0)
    video_path = tmp_path / "out" / "reel.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)

    def write_script(cand, checked, paid_generation):
        del paid_generation
        pack = generate_persian_story_package(
            fact_pack,
            editorial,
            complete=lambda prompt, context: package,
        )
        script = pipeline_script_from_package(pack)
        script["fact_pack"] = fact_pack
        return script

    def narrate(text, voice_id):
        del voice_id
        return {
            "path": str(audio_path),
            "provider": "fixture-silent",
            "usd": 0.0,
            "characters": len(text),
            "duration_seconds": 8.0,
            "voice_id": "silent",
        }

    def render_video(script, assets, audio):
        del script
        assert len(assets) == 4
        assert all(Path(asset["path"]).is_file() for asset in assets)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x0B1F3A:s=1080x1920:d=8",
                "-i",
                str(audio["path"]),
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(video_path),
            ],
            check=True,
            capture_output=True,
        )
        return {"path": str(video_path)}

    def probe_video(path):
        assert Path(path).is_file()
        return {
            "width": 1080,
            "height": 1920,
            "video_codec": "h264",
            "has_audio": True,
            "duration_seconds": 8.0,
            "audio_duration_seconds": 8.0,
            "checksum_sha256": "abc",
        }

    result = run_generation(
        config,
        store,
        now=now,
        scheduled=False,
        candidates=[candidate],
        verify_source=lambda item: {"ok": True, "excerpt": excerpt},
        write_script=write_script,
        find_assets=lambda cand, script: [
            {
                "path": str(photos[i]),
                "source_url": f"https://example.org/photo-{i}",
                "author": "",
                "license_name": "",
                "license_url": "",
                "kind": "licensed-photo",
                "role": "scene",
            }
            for i in range(4)
        ],
        narrate=narrate,
        render_video=render_video,
        probe_video=probe_video,
    )
    assert result.status == "qa_passed", result.message
    assert Path(result.detail.get("article_attempts", [{}])[0].get("url") or candidate.url)
    reel = store.get(result.reel_id)
    assert reel["local_status"] == "qa_passed"
    assert Path(reel["video_path"]).is_file()
    assert "۲۵۹" in (reel["narration_fa"] or "")
