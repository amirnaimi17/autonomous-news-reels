"""Phase 6 end-to-end Persian Reel pilot. OpenAI and ElevenLabs stay mocked."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.cli import main
from app.reels.commands import scene_assets_from_paths
from app.reels.pilot import narration_from_story, run_persian_reel_pilot
from app.reels.pipeline import Candidate
from app.reels.render import build_data_scenes, make_silent_mp3
from app.reels.store import ReelStore
from app.reels.voice import ARAN_VOICE, prepare_spoken

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "reel_pilot"
FIXTURE_STORY = FIXTURE_DIR / "story_package.json"
FIXTURE_AUDIO = FIXTURE_DIR / "narration.mp3"
FIXTURE_ASSET = FIXTURE_DIR / "scene-01.png"


@pytest.fixture
def story() -> dict:
    return json.loads(FIXTURE_STORY.read_text(encoding="utf-8"))


def _fake_remotion_runner(out: Path, audio: Path):
    def fake_runner(command, cwd, env):
        assert "DataReel" in command
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x0B1F3A:s=1080x1920:d=2",
                "-i",
                str(audio),
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(out),
            ],
            check=True,
            capture_output=True,
        )

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    return fake_runner


def test_narration_from_story_joins_scenes_in_order(story: dict) -> None:
    text = narration_from_story(story)
    assert "آزمون رندر" in text or "آزمون" in text
    assert text == " ".join(
        str(scene["narration"]).strip() for scene in story["scenes"] if scene.get("narration")
    )


def test_cli_asset_paths_stay_index_aligned_when_middle_file_missing(story: dict, tmp_path: Path) -> None:
    """Missing --asset slots must not pull later photos onto earlier scenes."""

    from app.reels.render import make_graphic_png

    first = tmp_path / "scene-01.png"
    third = tmp_path / "scene-03.png"
    make_graphic_png(first, color="0x112233")
    make_graphic_png(third, color="0x334455")
    missing = tmp_path / "missing-scene-02.jpg"
    assets = scene_assets_from_paths([first, missing, third, tmp_path / "also-missing.png"])
    assert len(assets) == 4
    assert assets[0]["path"] == str(first)
    assert assets[0]["author"] == "scene-01"
    assert assets[1]["path"] == ""
    assert assets[1]["author"] == ""
    assert assets[2]["path"] == str(third)
    assert assets[2]["author"] == "scene-03"
    assert assets[3]["path"] == ""

    scenes = build_data_scenes(story, assets=assets, audio_duration_seconds=8.0)
    assert [scene["graphic"] for scene in scenes] == [False, True, False, True]
    assert scenes[0]["source_image"] == str(first)
    assert scenes[0]["credit"] == "scene-01 / local-test"
    assert scenes[1]["source_image"] == ""
    assert scenes[1]["credit"] == ""
    assert scenes[2]["source_image"] == str(third)
    assert scenes[2]["credit"] == "scene-03 / local-test"
    assert scenes[3]["credit"] == ""


def test_offline_fixture_pilot_renders_qa_and_contact_sheet(story: dict, tmp_path: Path, monkeypatch) -> None:
    import app.reels.render as render_mod

    public = tmp_path / "public"
    public.mkdir()
    monkeypatch.setattr(render_mod, "PUBLIC", public)

    out_dir = tmp_path / "pilot-run"
    video = out_dir / "reel.mp4"
    db = tmp_path / "pilot.sqlite3"
    assets = [
        {
            "path": str(FIXTURE_ASSET),
            "author": "Fixture Photographer",
            "license_name": "CC0",
            "source_url": "https://example.org/fixture-asset",
            "role": "scene",
        },
        {"path": "", "author": "", "license_name": ""},
        {"path": "", "author": "", "license_name": ""},
        {"path": "", "author": "", "license_name": ""},
    ]

    result = run_persian_reel_pilot(
        out_dir=out_dir,
        run_id="phase6-offline",
        story_package=story,
        audio_path=FIXTURE_AUDIO,
        assets=assets,
        database_path=db,
        overwrite=True,
        render_runner=_fake_remotion_runner(video, FIXTURE_AUDIO),
    )

    assert result.status == "qa_passed"
    assert Path(result.story_package_path).is_file()
    assert Path(result.narration_path).read_text(encoding="utf-8").strip() == narration_from_story(story)
    assert Path(result.audio_path).is_file()
    assert Path(result.video_path).is_file()
    assert Path(result.contact_sheet_path).is_file()
    assert Path(result.qa_report_path).is_file()
    assert Path(result.report_path).is_file()

    report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert report["narration"] == narration_from_story(story)
    assert report["cron_enabled"] is False
    assert report["instagram_publish_enabled"] is False
    assert report["paid_api_calls"] is False

    qa = json.loads(Path(result.qa_report_path).read_text(encoding="utf-8"))
    assert qa["technical_pass"] is True
    names = {check["name"]: check["ok"] for check in qa["checks"]}
    assert names["resolution"] is True
    assert names["video_codec"] is True
    assert names["audio_codec"] is True
    assert names["duration"] is True
    assert names["file_integrity"] is True
    assert names["narration_present"] is True

    probe = qa["probe"]
    assert probe["width"] == 1080
    assert probe["height"] == 1920
    assert probe["video_codec"] in {"h264", "avc1"}
    assert probe["audio_codec"] == "aac"

    manifest = json.loads((out_dir / "audio" / "voice_manifest.json").read_text(encoding="utf-8"))
    assert manifest["narration"] == narration_from_story(story)
    assert manifest["voice_id"] == ARAN_VOICE
    assert manifest["espeak_used"] is False

    store = ReelStore(db)
    row = store.get("phase6-offline")
    assert row is not None
    assert row["narration_fa"] == narration_from_story(story)
    assert row["local_status"] == "qa_passed"


def test_mocked_openai_and_elevenlabs_pilot(tmp_path: Path, monkeypatch) -> None:
    import app.reels.render as render_mod

    public = tmp_path / "public"
    public.mkdir()
    monkeypatch.setattr(render_mod, "PUBLIC", public)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "unit-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-openai")

    now = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Kindergeld steigt ab Januar 2026 auf 259 Euro",
        summary=(
            "The federal government confirmed Kindergeld rises to 259 euro per child from January 2026. "
            "Families living in Germany keep the monthly payment."
        ),
        url="https://example.org/kindergeld-2026",
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )
    openai_calls: list[dict] = []
    voice_calls: list[dict] = []

    def script_complete(prompt: str, context):
        fact_pack = context["fact_pack"]
        url = fact_pack["sources"][0]["url"]
        openai_calls.append({"prompt": prompt, "url": url})
        return {
            "schema_version": "pilot-1",
            "event_id": fact_pack["event_id"],
            "language": "fa-IR",
            "audience": "Iranians living in Germany",
            "headline": "کمک‌هزینه فرزند از ژانویه ۲۰۲۶ به ۲۵۹ یورو می‌رسد",
            "source_urls": [url],
            "claims": [
                {"text": "Kindergeld rises to 259 euro per child from January 2026.", "source_urls": [url]},
                {"text": "Families living in Germany keep the monthly payment.", "source_urls": [url]},
            ],
            "duration_seconds": 8,
            "duration_policy": "completeness",
            "scenes": [
                {
                    "number": 1,
                    "duration_seconds": 2,
                    "narration": "خبر برای خانواده‌های مقیم آلمان: کمک‌هزینه فرزند تغییر می‌کند.",
                    "on_screen_text": "خبر خانواده",
                    "visual_prompt": "German federal ministry building exterior in Berlin, documentary photograph",
                },
                {
                    "number": 2,
                    "duration_seconds": 2,
                    "narration": "به گزارش بوندس‌رگیرونگ، از ژانویه 2026 این مبلغ به 259 یورو برای هر کودک می‌رسد.",
                    "on_screen_text": "۲۵۹ یورو",
                    "visual_prompt": "Euro banknotes and coins on a table, documentary photograph",
                },
                {
                    "number": 3,
                    "duration_seconds": 2,
                    "narration": "همان منبع نوشته خانواده‌های ساکن آلمان پرداخت ماهانه را حفظ می‌کنند.",
                    "on_screen_text": "پرداخت ماهانه",
                    "visual_prompt": "Residential mailbox with letters in a German hallway, real photograph",
                },
                {
                    "number": 4,
                    "duration_seconds": 2,
                    "narration": "این گزارش فقط همان ارقام تأییدشده را می‌گوید.",
                    "on_screen_text": "ارقام تأییدشده",
                    "visual_prompt": "Printed German benefits brochure on a desk, documentary photograph",
                },
            ],
            "disclaimers": ["Mocked OpenAI package. Never publish."],
        }

    def voice_transport(spec, key):
        voice_calls.append(spec)
        assert key == "unit-test-key"
        assert spec["body"]["model_id"] == "eleven_v4"
        assert spec["body"]["language_code"] == "fa"
        # Real silent bytes so ffprobe can still read duration after write.
        silent = tmp_path / "silent-source.mp3"
        if not silent.is_file():
            make_silent_mp3(silent, seconds=2.0)
        return silent.read_bytes()

    out_dir = tmp_path / "mocked-pilot"
    video = out_dir / "reel.mp4"
    # Runner will use the staged narration path after voice writes it.
    audio_dest = out_dir / "audio" / "narration.mp3"

    def runner(command, cwd, env):
        return _fake_remotion_runner(video, audio_dest)(command, cwd, env)

    result = run_persian_reel_pilot(
        out_dir=out_dir,
        run_id="phase6-mocked",
        candidate=candidate,
        checked={"ok": True, "excerpt": candidate.summary},
        script_complete=script_complete,
        voice_transport=voice_transport,
        voice_approved=False,
        database_path=tmp_path / "mocked.sqlite3",
        overwrite=True,
        render_runner=runner,
    )

    assert result.status == "qa_passed"
    assert openai_calls, "OpenAI completer must be invoked"
    assert voice_calls, "ElevenLabs transport must be invoked"
    narration = Path(result.narration_path).read_text(encoding="utf-8").strip()
    assert narration == narration_from_story(json.loads(Path(result.story_package_path).read_text(encoding="utf-8")))
    assert voice_calls[0]["body"]["text"] == prepare_spoken(narration)
    report = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert report["paid_api_calls"] is False
    assert report["cron_enabled"] is False


def test_pilot_refuses_overwrite_without_flag(story: dict, tmp_path: Path) -> None:
    out_dir = tmp_path / "existing"
    out_dir.mkdir()
    (out_dir / "story_package.json").write_text("{}", encoding="utf-8")
    result = run_persian_reel_pilot(
        out_dir=out_dir,
        story_package=story,
        audio_path=FIXTURE_AUDIO,
        skip_render=True,
        overwrite=False,
    )
    assert result.status == "failed"
    assert "overwrite" in result.message


def test_cli_run_persian_pilot_offline_skip_render(tmp_path: Path) -> None:
    out_dir = tmp_path / "cli-pilot"
    code = main(
        [
            "run-persian-pilot",
            "--story-package",
            str(FIXTURE_STORY),
            "--audio",
            str(FIXTURE_AUDIO),
            "--out-dir",
            str(out_dir),
            "--asset",
            str(FIXTURE_ASSET),
            "--database-path",
            str(tmp_path / "cli.sqlite3"),
            "--skip-render",
        ]
    )
    assert code == 0
    assert (out_dir / "story_package.json").is_file()
    assert (out_dir / "narration.txt").is_file()
    assert (out_dir / "audio" / "narration.mp3").is_file()
    assert (out_dir / "pilot_report.json").is_file()
    assert not (out_dir / "reel.mp4").exists()


def test_cli_run_persian_pilot_keeps_asset_slots_when_middle_missing(tmp_path: Path) -> None:
    """Phase 6 CLI must not compact --asset lists when a middle path is missing."""

    from app.reels.render import make_graphic_png

    first = tmp_path / "cli-scene-01.png"
    third = tmp_path / "cli-scene-03.png"
    make_graphic_png(first, color="0x112233")
    make_graphic_png(third, color="0x334455")
    missing = tmp_path / "cli-missing-scene-02.jpg"
    out_dir = tmp_path / "cli-asset-align"

    code = main(
        [
            "run-persian-pilot",
            "--story-package",
            str(FIXTURE_STORY),
            "--audio",
            str(FIXTURE_AUDIO),
            "--out-dir",
            str(out_dir),
            "--asset",
            str(first),
            "--asset",
            str(missing),
            "--asset",
            str(third),
            "--skip-render",
        ]
    )
    assert code == 0
    report = json.loads((out_dir / "pilot_report.json").read_text(encoding="utf-8"))
    assets = report["assets"]
    assert len(assets) == 3
    assert assets[0]["path"] == str(first)
    assert assets[0]["author"] == "cli-scene-01"
    assert assets[0]["license_name"] == "local-test"
    assert assets[1]["path"] == ""
    assert assets[1]["author"] == ""
    assert assets[1]["license_name"] == ""
    assert assets[2]["path"] == str(third)
    assert assets[2]["author"] == "cli-scene-03"
    assert assets[2]["license_name"] == "local-test"

    scenes = build_data_scenes(
        json.loads(FIXTURE_STORY.read_text(encoding="utf-8")),
        assets=assets,
        audio_duration_seconds=8.0,
    )
    assert [scene["graphic"] for scene in scenes] == [False, True, False, True]
    assert scenes[2]["source_image"] == str(third)
    assert scenes[2]["credit"] == "cli-scene-03 / local-test"
    assert scenes[1]["credit"] == ""
