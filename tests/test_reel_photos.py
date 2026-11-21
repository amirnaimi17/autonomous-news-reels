"""Licensed photograph retrieval and mandatory-photo gate. Network is mocked."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.reels.photos import (
    PhotoError,
    download_image,
    normalize_openverse_license,
    require_photographic_assets,
    search_openverse,
    validate_image_file,
)
from app.reels.render import build_data_scenes, make_silent_mp3
from app.reels.pilot import run_persian_reel_pilot


def _jpeg_bytes(path: Path) -> bytes:
    """Minimal valid-enough JPEG for header checks; ffprobe may still need a real file."""

    make = __import__("subprocess").run
    make(
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
    return path.read_bytes()


def test_normalize_openverse_license() -> None:
    assert normalize_openverse_license("by", "2.0") == "CC BY 2.0"
    assert normalize_openverse_license("by-sa", "4.0") == "CC BY-SA 4.0"
    assert normalize_openverse_license("cc0", None) == "CC0"
    assert "NC" in normalize_openverse_license("by-nc", "4.0").upper().replace("-", "")


def test_validate_image_file_accepts_jpeg(tmp_path: Path) -> None:
    path = tmp_path / "ok.jpg"
    _jpeg_bytes(path)
    meta = validate_image_file(path)
    assert meta["width"] >= 640
    assert meta["format"] == "JPEG"


def test_validate_image_file_rejects_html(tmp_path: Path) -> None:
    path = tmp_path / "bad.jpg"
    path.write_text("<html>too many requests</html>", encoding="utf-8")
    with pytest.raises(PhotoError, match="unsupported|corrupt"):
        validate_image_file(path)


def test_download_image_success_and_failure(tmp_path: Path) -> None:
    good = tmp_path / "source.jpg"
    _jpeg_bytes(good)
    payload = {"bytes": good.read_bytes()}

    def transport(request, timeout):
        url = request.full_url
        if "fail" in url:
            raise PhotoError("forced failure")
        return payload["bytes"]

    dest = tmp_path / "out.jpg"
    download_image("https://example.org/ok.jpg", dest, transport=transport, retries=1)
    assert dest.is_file()
    validate_image_file(dest)

    with pytest.raises(PhotoError):
        download_image("https://example.org/fail.jpg", tmp_path / "x.jpg", transport=transport, retries=1)


def test_search_openverse_filters_noncommercial(tmp_path: Path) -> None:
    body = {
        "results": [
            {
                "title": "good",
                "url": "https://live.staticflickr.com/1/good.jpg",
                "foreign_landing_url": "https://flickr.com/good",
                "creator": "A",
                "license": "by",
                "license_version": "2.0",
                "license_url": "https://creativecommons.org/licenses/by/2.0/",
                "provider": "flickr",
                "width": 1000,
                "height": 800,
                "attribution": "A / CC BY 2.0",
            },
            {
                "title": "bad-nc",
                "url": "https://live.staticflickr.com/1/bad.jpg",
                "foreign_landing_url": "https://flickr.com/bad",
                "creator": "B",
                "license": "by-nc",
                "license_version": "2.0",
                "license_url": "https://creativecommons.org/licenses/by-nc/2.0/",
                "provider": "flickr",
                "width": 1000,
                "height": 800,
            },
        ]
    }

    def transport(request, timeout):
        return json.dumps(body).encode("utf-8")

    found = search_openverse("Bundesrat", transport=transport)
    assert len(found) == 1
    assert found[0].license_name == "CC BY 2.0"
    assert found[0].author == "A"


def test_require_photographic_assets_detects_missing_and_graphics(tmp_path: Path) -> None:
    photo = tmp_path / "p.jpg"
    _jpeg_bytes(photo)
    ok = {
        "path": str(photo),
        "source_url": "https://example.org/p",
        "author": "Photographer",
        "license_name": "CC BY 2.0",
    }
    problems = require_photographic_assets([ok, {"path": "", "license_name": "", "author": "", "source_url": ""}], expected_scenes=2)
    assert any("scene 2" in item for item in problems)

    graphic = {**ok, "license_name": "original-graphic"}
    problems = require_photographic_assets([ok, graphic, ok, ok], expected_scenes=4)
    assert any("graphic placeholder" in item for item in problems)


def test_scene_asset_mapping_keeps_index_with_photos(tmp_path: Path) -> None:
    story = {
        "scenes": [
            {"number": 1, "duration_seconds": 2, "narration": "یک", "on_screen_text": "۱"},
            {"number": 2, "duration_seconds": 2, "narration": "دو", "on_screen_text": "۲"},
            {"number": 3, "duration_seconds": 2, "narration": "سه", "on_screen_text": "۳"},
            {"number": 4, "duration_seconds": 2, "narration": "چهار", "on_screen_text": "۴"},
        ]
    }
    photos = []
    for index in range(4):
        path = tmp_path / f"s{index}.jpg"
        _jpeg_bytes(path)
        photos.append(
            {
                "path": str(path),
                "author": f"Author{index}",
                "license_name": "CC BY 2.0",
                "source_url": f"https://example.org/{index}",
            }
        )
    # Missing middle file must not shift later photos.
    photos[1]["path"] = str(tmp_path / "missing.jpg")
    scenes = build_data_scenes(story, assets=photos, audio_duration_seconds=8)
    assert scenes[0]["graphic"] is False
    assert scenes[1]["graphic"] is True
    assert scenes[2]["graphic"] is False
    assert scenes[2]["credit"] == "Author2 / CC BY 2.0"


def test_rerender_reuses_audio_and_does_not_call_tts(tmp_path: Path, monkeypatch) -> None:
    story = {
        "schema_version": "pilot-1",
        "event_id": "photo-rerender",
        "language": "fa-IR",
        "audience": "test",
        "headline": "آزمون",
        "source_urls": ["https://example.org/x"],
        "claims": [{"text": "x", "source_urls": ["https://example.org/x"]}],
        "duration_seconds": 4,
        "scenes": [
            {"number": i, "duration_seconds": 1, "narration": f"متن {i}", "on_screen_text": str(i), "visual_prompt": "p"}
            for i in range(1, 5)
        ],
        "disclaimers": [],
    }
    audio = tmp_path / "narration.mp3"
    make_silent_mp3(audio, seconds=2.0)
    assets = []
    for index in range(4):
        path = tmp_path / f"photo-{index}.jpg"
        _jpeg_bytes(path)
        assets.append(
            {
                "path": str(path),
                "author": f"A{index}",
                "license_name": "CC BY 2.0",
                "source_url": f"https://example.org/{index}",
            }
        )

    called = {"voice": 0}

    def boom(*args, **kwargs):
        called["voice"] += 1
        raise AssertionError("TTS must not run during photo re-render")

    monkeypatch.setattr("app.reels.pilot.narrate_persian", boom)
    import app.reels.render as render_mod

    public = tmp_path / "public"
    public.mkdir()
    monkeypatch.setattr(render_mod, "PUBLIC", public)

    out = tmp_path / "out"
    video = out / "reel.mp4"

    def fake_runner(command, cwd, env):
        import subprocess

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=0x224466:s=1080x1920:d=2",
                "-i",
                str(audio),
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(video),
            ],
            check=True,
            capture_output=True,
        )

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    result = run_persian_reel_pilot(
        out_dir=out,
        story_package=story,
        audio_path=audio,
        assets=assets,
        overwrite=True,
        render_runner=fake_runner,
    )
    assert called["voice"] == 0
    assert result.status == "qa_passed"
    assert Path(result.audio_path).read_bytes() == audio.read_bytes() or Path(result.audio_path).is_file()
