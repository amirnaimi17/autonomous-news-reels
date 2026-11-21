"""Phase 4 ElevenLabs Aran narration. All HTTP is mocked."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.cli import main
from app.reels.commands import narrate_aran
from app.reels.config import ReelConfig
from app.reels.pipeline import Candidate, run_generation
from app.reels.store import ReelStore
from app.reels.voice import ARAN_VOICE, narrate_persian, prepare_spoken, production_voice_id


def _licensed_photos(tmp_path: Path, count: int = 4) -> list[dict]:
    import subprocess

    assets = []
    for index in range(count):
        path = tmp_path / f"voice-photo-{index}.jpg"
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
                "source_url": f"https://example.org/voice/{index}",
                "author": f"Author{index}",
                "license_name": "CC BY 2.0",
                "license_url": "https://creativecommons.org/licenses/by/2.0/",
                "kind": "licensed-photo",
                "role": "scene",
            }
        )
    return assets


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
        voice_id=ARAN_VOICE,
        max_attempts=3,
        script_provider="off",
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
    base.update(overrides)
    return ReelConfig(**base)


def test_production_voice_is_aran() -> None:
    assert production_voice_id() == ARAN_VOICE


def test_live_call_is_refused_without_approval(tmp_path: Path) -> None:
    calls: list[object] = []

    def transport(spec, key):
        calls.append(spec)
        raise AssertionError("network must not run")

    with pytest.raises(RuntimeError, match="disabled"):
        narrate_persian(
            "خبر کوتاه برای آزمون صدا.",
            ARAN_VOICE,
            out_path=tmp_path / "out.mp3",
            approved=False,
            transport=None,
            ledger_path=tmp_path / "ledger.jsonl",
        )
    assert calls == []


def test_mocked_transport_writes_mp3_and_pipeline_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "unit-test-key")
    seen: dict = {}

    def transport(spec, key):
        seen["key"] = key
        seen["spec"] = spec
        assert key == "unit-test-key"
        assert "unit-test-key" not in json.dumps(spec)
        assert spec["body"]["model_id"] == "eleven_v4"
        assert spec["body"]["language_code"] == "fa"
        assert spec["url"].endswith(f"/v1/text-to-speech/{ARAN_VOICE}")
        return b"ID3mocked-mp3-bytes"

    out = tmp_path / "narration.mp3"
    result = narrate_aran(
        "کمک‌هزینه فرزند از ژانویه 2026 به 259 یورو می‌رسد.",
        ARAN_VOICE,
        transport=transport,
        config=_config(tmp_path),
        out_path=out,
        approved=False,  # transport injection is enough for tests
    )
    assert out.is_file()
    assert out.read_bytes().startswith(b"ID3")
    assert result["provider"] == "elevenlabs"
    assert result["voice_id"] == ARAN_VOICE
    assert result["model_id"] == "eleven_v4"
    assert result["speed"] == 1.0
    assert result["duration_seconds"] > 0
    assert result["characters"] > 0
    assert result["usd"] > 0
    assert seen["spec"]["body"]["text"] == prepare_spoken(
        "کمک‌هزینه فرزند از ژانویه 2026 به 259 یورو می‌رسد."
    )


def test_speak_narration_dry_run_does_not_send(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REEL_WORKING_DIRECTORY", str(tmp_path))
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    code = main(
        [
            "speak-narration",
            "--text",
            "خبر کوتاه برای آزمون صدا.",
        ]
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["sent"] is False
    assert payload["request"]["body"]["model_id"] == "eleven_v4"


def test_paid_generation_false_still_blocks_before_voice(tmp_path: Path) -> None:
    config = _config(tmp_path, paid_generation=False)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Kindergeld rises to 259 euro in 2026",
        summary="The federal government confirmed Kindergeld rises to 259 euro per child from January 2026.",
        url="https://example.com/kindergeld-voice",
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )
    voice_calls: list[str] = []

    def narrate(text, voice_id):
        voice_calls.append(text)
        raise AssertionError("voice must not run when paid generation is off")

    result = run_generation(
        config,
        store,
        now=now,
        scheduled=False,
        candidates=[candidate],
        verify_source=lambda item: {"ok": True, "excerpt": item.summary},
        write_script=lambda candidate, checked, paid_generation: {
            "status": "ready",
            "narration": "خبر کوتاه.",
            "caption": "خبر",
            "angle": "عنوان",
            "storyboard_json": "[]",
            "voice_estimate_usd": 0.01,
        },
        find_assets=lambda candidate, script: _licensed_photos(tmp_path),
        narrate=narrate,
        render_video=lambda *a, **k: (_ for _ in ()).throw(AssertionError("video")),
        probe_video=lambda path: (_ for _ in ()).throw(AssertionError("probe")),
    )
    assert result.status == "blocked_paid"
    assert voice_calls == []


def test_pipeline_with_mocked_voice_stops_before_forcing_live_video(tmp_path: Path, monkeypatch) -> None:
    """With paid generation on, narrate runs; video stays a separate concern and is mocked to fail closed."""

    monkeypatch.setenv("ELEVENLABS_API_KEY", "unit-test-key")
    config = _config(tmp_path, paid_generation=True, elevenlabs_approved=True, per_reel_max_usd=1.0)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Kindergeld rises to 259 euro in 2026",
        summary="The federal government confirmed Kindergeld rises to 259 euro per child from January 2026.",
        url="https://example.com/kindergeld-voice-2",
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )

    def transport(spec, key):
        return b"ID3pipeline-mock"

    def narrate(text, voice_id):
        return narrate_aran(
            text,
            voice_id,
            transport=transport,
            config=config,
            out_path=tmp_path / "audio" / "pipeline.mp3",
            approved=True,
        )

    result = run_generation(
        config,
        store,
        now=now,
        scheduled=False,
        candidates=[candidate],
        verify_source=lambda item: {"ok": True, "excerpt": item.summary},
        write_script=lambda candidate, checked, paid_generation: {
            "status": "ready",
            "narration": "خبر کوتاه برای خانواده در آلمان.",
            "caption": "خبر",
            "angle": "عنوان",
            "storyboard_json": "[]",
            "voice_estimate_usd": 0.01,
        },
        find_assets=lambda candidate, script: _licensed_photos(tmp_path),
        narrate=narrate,
        render_video=lambda script, assets, audio: (_ for _ in ()).throw(RuntimeError("video disabled in this test")),
        probe_video=lambda path: {},
    )
    assert result.status == "failed"
    assert "video disabled" in result.message
    assert (tmp_path / "audio" / "pipeline.mp3").is_file()
    # Audio row is only stored after both narrate and render succeed in the current pipeline.
    # The MP3 file itself must still exist from the successful narrate step.
    assert store.get(result.reel_id) is not None
