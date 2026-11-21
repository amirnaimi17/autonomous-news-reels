"""AI editorial ranking over retrieved RSS candidates. LLM is always mocked."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.exceptions import GroundingError
from app.reels.config import ReelConfig
from app.reels.pipeline import Candidate, run_generation, select_story
from app.reels.store import ReelStore
from app.services.news.editorial_rank import (
    assign_article_ids,
    parse_ranking_response,
    rank_retrieved_articles,
)


def _config(tmp_path: Path, **overrides) -> ReelConfig:
    audiences = tmp_path / "editorial_audiences.json"
    if not audiences.is_file():
        audiences.write_text(
            json.dumps(
                {
                    "iranians_in_germany": {
                        "id": "iranians_in_germany",
                        "label": "Persian-speaking residents of Germany",
                        "content_categories": ["housing_and_rent", "work_and_wages"],
                        "selection_notes": ["Do not require Iran mentions."],
                        "min_score": 0.60,
                    }
                }
            )
            + "\n",
            encoding="utf-8",
        )
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
        script_provider="off",
        script_model="gpt-4o-mini",
        script_output_dir=tmp_path / "scripts",
        elevenlabs_approved=False,
        audio_output_dir=tmp_path / "audio",
        editorial_rank_provider="openai",
        editorial_rank_approved=True,
        editorial_audience_id="iranians_in_germany",
        editorial_min_score=None,
        editorial_audiences_file=audiences,
    )
    base.update(overrides)
    return ReelConfig(**base)


def _candidate(title: str, url: str, summary: str, when: datetime) -> Candidate:
    return Candidate(
        title=title,
        summary=summary,
        url=url,
        publisher="Tagesschau",
        published_at=when,
        category="policy",
    )


def test_profile_min_score_used_unless_explicitly_overridden(tmp_path: Path) -> None:
    audiences = tmp_path / "audiences.json"
    audiences.write_text(
        json.dumps(
            {
                "iranians_in_germany": {
                    "id": "iranians_in_germany",
                    "label": "Persian-speaking residents of Germany",
                    "min_score": 0.72,
                    "content_categories": ["housing_and_rent"],
                    "selection_notes": [],
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    candidates = [
        _candidate("Rent news", "https://example.com/rent-score", "Tenants in Germany.", now),
    ]

    def complete_reject(prompt: str, context=None, **kwargs):
        assert "Minimum suitable score: 0.72" in prompt
        return {
            "rankings": [
                {
                    "id": "c01",
                    "score": 0.65,
                    "relevance": "Housing.",
                    "suitable": True,
                }
            ],
            "selected_id": "c01",
            "rejection_reason": "",
        }

    from app.services.news.editorial_rank import prepare_ranking_request, rank_retrieved_articles

    prepared = prepare_ranking_request(
        candidates,
        audiences_file=audiences,
        min_score=None,
    )
    assert prepared["min_score"] == 0.72
    assert prepared["profile"].min_score == 0.72

    # Score 0.65 is below profile 0.72 → unsuitable even if model marked suitable.
    ranking = rank_retrieved_articles(
        candidates,
        audiences_file=audiences,
        min_score=None,
        complete=complete_reject,
    )
    assert ranking.status == "rejected"
    assert ranking.min_score == 0.72

    def complete_ok(prompt: str, context=None, **kwargs):
        assert "Minimum suitable score: 0.40" in prompt
        return {
            "rankings": [
                {
                    "id": "c01",
                    "score": 0.65,
                    "relevance": "Housing.",
                    "practical_impact": "Rent.",
                    "newsworthiness": "Policy.",
                    "audience_interest": "Housing.",
                    "freshness": "Now.",
                    "suitable": True,
                }
            ],
            "selected_id": "c01",
            "rejection_reason": "",
        }

    overridden = rank_retrieved_articles(
        candidates,
        audiences_file=audiences,
        min_score=0.40,
        complete=complete_ok,
    )
    assert overridden.status == "selected"
    assert overridden.min_score == 0.40


def test_assign_ids_and_reject_invented_ids() -> None:
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    rows = assign_article_ids(
        [
            _candidate("Rent brake update", "https://example.com/a", "Housing change in Germany.", now),
            _candidate("Sports final", "https://example.com/b", "A match result.", now),
        ]
    )
    by_id = {row["id"]: row for row in rows}
    with pytest.raises(GroundingError, match="invented article id"):
        parse_ranking_response(
            {
                "rankings": [{"id": "https://evil.example/x", "score": 0.9, "relevance": "x", "suitable": True}],
                "selected_id": "https://evil.example/x",
            },
            by_id,
            min_score=0.55,
        )


def test_rank_retrieved_articles_returns_top_three(tmp_path: Path) -> None:
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    candidates = [
        _candidate(
            "Mietpreisbremse extended",
            "https://example.com/rent",
            "Tenants in Germany keep rent protections.",
            now,
        ),
        _candidate(
            "Bundesliga scores",
            "https://example.com/sport",
            "Football results from Saturday.",
            now,
        ),
        _candidate(
            "Mindestlohn rises",
            "https://example.com/wage",
            "Workers in Germany receive a higher minimum wage.",
            now,
        ),
        _candidate(
            "Celebrity wedding",
            "https://example.com/celeb",
            "Entertainment news.",
            now,
        ),
    ]

    def complete(prompt: str, context=None, **kwargs):
        assert "c01" in prompt and "c04" in prompt
        assert "https://evil" not in prompt
        return {
            "rankings": [
                {
                    "id": "c03",
                    "score": 0.91,
                    "relevance": "Wage floor affects residents' income.",
                    "practical_impact": "Higher monthly pay.",
                    "newsworthiness": "Policy change.",
                    "audience_interest": "Work and money.",
                    "freshness": "Current.",
                    "suitable": True,
                },
                {
                    "id": "c01",
                    "score": 0.84,
                    "relevance": "Housing cost control for tenants.",
                    "practical_impact": "Rent stability.",
                    "newsworthiness": "Legal extension.",
                    "audience_interest": "Housing.",
                    "freshness": "Current.",
                    "suitable": True,
                },
                {
                    "id": "c02",
                    "score": 0.12,
                    "relevance": "Sports only.",
                    "suitable": False,
                },
            ],
            "selected_id": "c03",
            "rejection_reason": "",
        }

    ranking = rank_retrieved_articles(candidates, complete=complete)
    assert ranking.status == "selected"
    assert ranking.selected_id == "c03"
    assert ranking.selected.url == "https://example.com/wage"
    assert len(ranking.top) == 3
    assert ranking.top[0].url == "https://example.com/wage"
    assert ranking.top[1].url == "https://example.com/rent"
    assert all(item.url.startswith("https://example.com/") for item in ranking.top)


def test_rank_rejects_when_none_suitable() -> None:
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    candidates = [
        _candidate("World Cup draw", "https://example.com/wc", "Tournament bracket news.", now),
    ]

    def complete(prompt: str, context=None, **kwargs):
        return {
            "rankings": [
                {
                    "id": "c01",
                    "score": 0.2,
                    "relevance": "No household impact in Germany.",
                    "suitable": False,
                }
            ],
            "selected_id": None,
            "rejection_reason": "no practical Germany household impact",
        }

    ranking = rank_retrieved_articles(candidates, complete=complete)
    assert ranking.status == "rejected"
    assert "household" in ranking.message
    assert ranking.selected is None
    assert len(ranking.top) == 1


def test_pipeline_ai_selection_before_script(tmp_path: Path) -> None:
    import subprocess

    config = _config(tmp_path)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    # Keyword filter would reject this (no clear household token); AI can still pick it.
    candidates = [
        _candidate(
            "Health insurance contribution change",
            "https://example.com/health",
            "Employees in Germany face updated health-insurance contribution rates.",
            now,
        ),
        _candidate(
            "Hollywood awards",
            "https://example.com/awards",
            "Entertainment ceremony coverage.",
            now,
        ),
    ]
    for i in range(4):
        path = tmp_path / f"p{i}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=800x600:d=0.1", "-frames:v", "1", str(path)],
            check=True,
            capture_output=True,
        )

    def complete(prompt: str, context=None, **kwargs):
        return {
            "rankings": [
                {
                    "id": "c01",
                    "score": 0.88,
                    "relevance": "Insurance costs affect residents' monthly budgets.",
                    "practical_impact": "Payroll deductions change.",
                    "newsworthiness": "Nationwide rate update.",
                    "audience_interest": "Health costs.",
                    "freshness": "Current.",
                    "suitable": True,
                },
                {
                    "id": "c02",
                    "score": 0.05,
                    "relevance": "Entertainment only.",
                    "suitable": False,
                },
            ],
            "selected_id": "c01",
            "rejection_reason": "",
        }

    result = run_generation(
        config,
        store,
        now=now,
        scheduled=False,
        candidates=candidates,
        verify_source=lambda item: {"ok": True, "excerpt": item.summary},
        write_script=lambda candidate, checked, paid_generation: {
            "status": "ready",
            "narration": "خبر کوتاه.",
            "caption": "خبر",
            "angle": "بیمه",
            "storyboard_json": "[]",
            "voice_estimate_usd": 0.01,
        },
        find_assets=lambda candidate, script: [
            {
                "path": str(tmp_path / f"p{i}.jpg"),
                "source_url": f"https://example.org/{i}",
                "author": f"A{i}",
                "license_name": "CC BY 2.0",
                "license_url": "https://creativecommons.org/licenses/by/2.0/",
                "kind": "licensed-photo",
                "role": "scene",
            }
            for i in range(4)
        ],
        narrate=lambda *a, **k: (_ for _ in ()).throw(AssertionError("ElevenLabs must not run")),
        render_video=lambda *a, **k: (_ for _ in ()).throw(AssertionError("render")),
        probe_video=lambda path: {},
        rank_complete=complete,
    )
    assert result.status == "blocked_paid"
    assert result.detail["selection"] == "ai"
    assert result.detail["ranking"]["selected_id"] == "c01"
    assert len(result.detail["ranking"]["top"]) == 2
    assert result.detail["ranking"]["top"][0]["url"] == "https://example.com/health"
    assert result.detail["ranking"]["top"][0]["score"] == 0.88


def test_ai_ranking_unapproved_does_not_call_llm(tmp_path: Path) -> None:
    config = _config(tmp_path, editorial_rank_approved=False)
    store = ReelStore(config.database_path)
    store.migrate()
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    candidates = [
        _candidate("Rent news", "https://example.com/rent2", "Tenants in Germany.", now),
    ]
    calls = {"n": 0}

    def complete(prompt: str, context=None, **kwargs):
        calls["n"] += 1
        raise AssertionError("LLM must not run without approval")

    candidate, reason, detail = select_story(
        candidates,
        store,
        now,
        config.news_window_hours,
        config=config,
        rank_complete=None,  # live path blocked by approval
    )
    assert candidate is None
    assert reason == "editorial ranking not approved"
    assert calls["n"] == 0


def test_duplicate_still_blocks_ai_selection(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ReelStore(config.database_path)
    store.migrate()
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate(
        "Mindestlohn rises again",
        "https://example.com/wage2",
        "Minimum wage rises for workers in Germany.",
        now,
    )

    def complete(prompt: str, context=None, **kwargs):
        return {
            "rankings": [
                {
                    "id": "c01",
                    "score": 0.9,
                    "relevance": "Wage change.",
                    "practical_impact": "Income.",
                    "newsworthiness": "Policy.",
                    "audience_interest": "Work.",
                    "freshness": "Now.",
                    "suitable": True,
                }
            ],
            "selected_id": "c01",
            "rejection_reason": "",
        }

    # First selection succeeds into blocked_paid after photos
    import subprocess

    for i in range(4):
        path = tmp_path / f"d{i}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=800x600:d=0.1", "-frames:v", "1", str(path)],
            check=True,
            capture_output=True,
        )

    first = run_generation(
        config,
        store,
        now=now,
        scheduled=False,
        candidates=[candidate],
        verify_source=lambda item: {"ok": True, "excerpt": item.summary},
        write_script=lambda candidate, checked, paid_generation: {
            "status": "ready",
            "narration": "خبر.",
            "caption": "خبر",
            "angle": "a",
            "storyboard_json": "[]",
            "voice_estimate_usd": 0.01,
        },
        find_assets=lambda candidate, script: [
            {
                "path": str(tmp_path / f"d{i}.jpg"),
                "source_url": f"https://example.org/d{i}",
                "author": f"A{i}",
                "license_name": "CC BY 2.0",
                "license_url": "https://creativecommons.org/licenses/by/2.0/",
                "kind": "licensed-photo",
                "role": "scene",
            }
            for i in range(4)
        ],
        narrate=lambda *a, **k: {},
        render_video=lambda *a, **k: {},
        probe_video=lambda path: {},
        rank_complete=complete,
    )
    assert first.status == "blocked_paid"

    # Force terminal-like duplicate by marking packaged
    row = store.get(first.reel_id)
    store.upsert_reel({**dict(row), "local_status": "queued"})

    second = select_story(
        [candidate],
        store,
        now,
        config.news_window_hours,
        config=config,
        rank_complete=complete,
    )
    assert second[0] is None
    assert second[1] == "duplicate"


def test_rank_news_cli_prints_top_three_without_media(tmp_path: Path, monkeypatch, capsys) -> None:
    from app.cli import main
    from app.reels.commands import rank_news_command

    config = _config(tmp_path, editorial_rank_provider="off", editorial_rank_approved=False)
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
    candidates = [
        _candidate(
            "Mietpreisbremse extended",
            "https://example.com/rent-cli",
            "Tenants in Germany keep rent protections.",
            now,
        ),
        _candidate(
            "Sports score",
            "https://example.com/sport-cli",
            "Football results.",
            now,
        ),
        _candidate(
            "Mindestlohn rises",
            "https://example.com/wage-cli",
            "Workers in Germany receive a higher wage floor.",
            now,
        ),
    ]

    monkeypatch.setattr("app.reels.commands.discover_candidates", lambda cfg, moment: candidates)
    monkeypatch.setattr("app.reels.commands.load_reel_config", lambda: config)

    # Without approve: estimate only, no LLM.
    code = rank_news_command(limit=20, approve=False, now=now, config=config)
    out = capsys.readouterr().out
    assert code == 0
    assert "usage_estimate:" in out
    assert "editorial ranking not approved" in out
    assert "no OpenAI call was made" in out

    calls = {"n": 0}

    def complete(prompt: str, context=None, **kwargs):
        calls["n"] += 1
        return {
            "rankings": [
                {
                    "id": "c03",
                    "score": 0.93,
                    "relevance": "Wage floor for workers.",
                    "practical_impact": "Income.",
                    "newsworthiness": "Policy.",
                    "audience_interest": "Work.",
                    "freshness": "Now.",
                    "suitable": True,
                },
                {
                    "id": "c01",
                    "score": 0.81,
                    "relevance": "Housing protections.",
                    "practical_impact": "Rent.",
                    "newsworthiness": "Law.",
                    "audience_interest": "Housing.",
                    "freshness": "Now.",
                    "suitable": True,
                },
                {
                    "id": "c02",
                    "score": 0.1,
                    "relevance": "Sports.",
                    "suitable": False,
                },
            ],
            "selected_id": "c03",
            "rejection_reason": "",
        }

    code = rank_news_command(limit=20, approve=True, now=now, config=config, complete=complete)
    out = capsys.readouterr().out
    assert code == 0
    assert calls["n"] == 1
    assert "editorial_top3:" in out
    assert "https://example.com/wage-cli" in out
    assert "https://example.com/rent-cli" in out
    assert "score=0.93" in out
    assert "relevance: Wage floor" in out
    # No media pipeline markers.
    assert "ElevenLabs" not in out
    assert "Remotion" not in out

    # CLI wiring
    monkeypatch.setattr(
        "app.reels.commands.rank_news_command",
        lambda **kwargs: 0 if kwargs.get("limit") == 20 else 1,
    )
    assert main(["rank-news", "--limit", "20"]) == 0


def test_load_reel_config_min_score_override(monkeypatch, tmp_path: Path) -> None:
    from app.reels.config import load_reel_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REEL_WORKING_DIRECTORY", str(tmp_path))
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=sk-test-from-dotenv\n"
        "REEL_EDITORIAL_RANK_PROVIDER=openai\n"
        "REEL_EDITORIAL_RANK_APPROVED=true\n"
        "REEL_EDITORIAL_AUDIENCE_ID=iranians_in_germany\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("REEL_EDITORIAL_MIN_SCORE", raising=False)
    monkeypatch.delenv("REEL_EDITORIAL_RANK_APPROVED", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = load_reel_config()
    assert config.editorial_min_score is None
    assert config.editorial_rank_approved is True
    assert config.editorial_rank_provider == "openai"
    import os

    assert os.environ.get("OPENAI_API_KEY") == "sk-test-from-dotenv"

    monkeypatch.setenv("REEL_EDITORIAL_MIN_SCORE", "0.41")
    config = load_reel_config()
    assert config.editorial_min_score == 0.41
