"""Phase 5 Remotion DataReel rendering. No OpenAI or ElevenLabs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.reels.render import (
    RenderError,
    build_data_scenes,
    make_silent_mp3,
    probe_media,
    render_data_reel,
    stage_render_bundle,
    validate_reel_probe,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_STORY = ROOT / "tests" / "fixtures" / "reel_render" / "story_package.json"


@pytest.fixture
def story() -> dict:
    return json.loads(FIXTURE_STORY.read_text(encoding="utf-8"))


def test_build_data_scenes_scales_to_audio_and_marks_graphics(story: dict, tmp_path: Path) -> None:
    photo = tmp_path / "photo.png"
    # Missing path for scene 1 only -> graphic for that scene.
    scenes = build_data_scenes(story, assets=[{"path": str(photo)}], audio_duration_seconds=8.0)
    assert len(scenes) == 4
    assert sum(scene["durationFrames"] for scene in scenes) == 240
    assert scenes[0]["graphic"] is True
    assert scenes[0]["credit"] == ""
    assert "آزمون" in scenes[0]["headline"] or "رندر" in scenes[0]["headline"]


def test_missing_image_does_not_shift_later_scene_assets(story: dict, tmp_path: Path) -> None:
    """A hole in the asset list must not pull later photos into earlier scenes."""

    from app.reels.render import make_graphic_png

    first = tmp_path / "scene-01.png"
    third = tmp_path / "scene-03.png"
    make_graphic_png(first, color="0x112233")
    make_graphic_png(third, color="0x334455")
    assets = [
        {"path": str(first), "author": "Alice", "license_name": "CC-BY-4.0"},
        {"path": str(tmp_path / "missing-scene-02.jpg"), "author": "Bob", "license_name": "CC0"},
        {"path": str(third), "author": "Carol", "license_name": "CC-BY-SA"},
        {"path": "", "author": "Dan", "license_name": "unused"},
    ]
    scenes = build_data_scenes(story, assets=assets, audio_duration_seconds=8.0)
    assert scenes[0]["graphic"] is False
    assert scenes[0]["source_image"] == str(first)
    assert scenes[0]["credit"] == "Alice / CC-BY-4.0"
    assert scenes[1]["graphic"] is True
    assert scenes[1]["source_image"] == ""
    assert scenes[1]["credit"] == ""
    assert scenes[2]["graphic"] is False
    assert scenes[2]["source_image"] == str(third)
    assert scenes[2]["credit"] == "Carol / CC-BY-SA"
    assert scenes[3]["graphic"] is True
    assert scenes[3]["credit"] == ""


def test_mixed_image_and_graphic_scenes_keep_index_alignment(story: dict, tmp_path: Path) -> None:
    from app.reels.render import make_graphic_png

    photo = tmp_path / "only-scene-2.png"
    make_graphic_png(photo, color="0x556677")
    assets = [
        {"path": "", "author": "skip"},
        {"path": str(photo), "author": "Photographer", "license_name": "Pexels"},
        {"path": str(tmp_path / "gone.png"), "author": "Ghost", "license_name": "CC0"},
    ]
    scenes = build_data_scenes(story, assets=assets, audio_duration_seconds=4.0)
    assert [scene["graphic"] for scene in scenes] == [True, False, True, True]
    assert scenes[1]["source_image"] == str(photo)
    assert scenes[1]["credit"] == "Photographer / Pexels"
    assert scenes[2]["source_image"] == ""
    assert scenes[2]["credit"] == ""


def test_stage_bundle_copies_audio_and_creates_graphic_plates(story: dict, tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "narration.mp3"
    make_silent_mp3(audio, seconds=2.0)
    # Stage into a temp public dir by monkeypatching PUBLIC
    import app.reels.render as render_mod

    public = tmp_path / "public"
    public.mkdir()
    monkeypatch.setattr(render_mod, "PUBLIC", public)
    bundle = stage_render_bundle(story, audio, render_id="unit-stage", audio_duration_seconds=2.0)
    props = bundle["props"]
    assert props["audioFile"].endswith("narration.mp3")
    assert (public / props["audioFile"]).is_file()
    assert len(props["scenes"]) == 4
    for scene in props["scenes"]:
        assert scene["image"]
        assert (public / scene["image"]).is_file()
        assert scene["graphic"] is True


def test_render_refuses_overwrite(story: dict, tmp_path: Path, monkeypatch) -> None:
    audio = tmp_path / "narration.mp3"
    make_silent_mp3(audio, seconds=1.0)
    out = tmp_path / "exists.mp4"
    out.write_bytes(b"not-a-real-mp4")
    import app.reels.render as render_mod

    monkeypatch.setattr(render_mod, "PUBLIC", tmp_path / "public")
    (tmp_path / "public").mkdir()

    def fake_runner(command, cwd, env):
        raise AssertionError("runner must not be called when overwrite is false")

    with pytest.raises(RenderError, match="overwrite"):
        render_data_reel(story, audio, out_path=out, overwrite=False, runner=fake_runner)


def test_validate_probe_accepts_vertical_h264() -> None:
    probe = {
        "width": 1080,
        "height": 1920,
        "video_codec": "h264",
        "audio_codec": "aac",
        "has_audio": True,
        "duration_seconds": 8.0,
    }
    assert validate_reel_probe(probe) == []
    assert "resolution" in validate_reel_probe({**probe, "width": 720})
    assert "audio codec" in validate_reel_probe({**probe, "audio_codec": "mp3"})
    assert "audio codec" in validate_reel_probe({**probe, "audio_codec": "opus"})


def test_mocked_runner_writes_validated_mp4(story: dict, tmp_path: Path, monkeypatch) -> None:
    """Unit path: fake Remotion by writing a real short vertical MP4 with ffmpeg."""

    audio = tmp_path / "narration.mp3"
    make_silent_mp3(audio, seconds=2.0)
    import app.reels.render as render_mod

    public = tmp_path / "public"
    public.mkdir()
    monkeypatch.setattr(render_mod, "PUBLIC", public)
    out = tmp_path / "out.mp4"

    def fake_runner(command, cwd, env):
        assert "DataReel" in command
        assert any(str(out) == part for part in command)
        # Encode a tiny vertical H.264+AAC file that ffprobe accepts.
        import subprocess

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

    result = render_data_reel(story, audio, out_path=out, overwrite=True, runner=fake_runner, render_id="mock-run")
    assert result["ok"] is True
    assert Path(result["path"]).is_file()
    probe = probe_media(out)
    assert probe["width"] == 1080
    assert probe["height"] == 1920
    assert probe["has_audio"] is True
