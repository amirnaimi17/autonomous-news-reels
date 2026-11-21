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
        "license_url": "https://creativecommons.org/licenses/by/2.0/",
    }
    problems = require_photographic_assets(
        [ok, {"path": "", "license_name": "", "author": "", "source_url": "", "license_url": ""}],
        expected_scenes=2,
    )
    assert any("scene 2" in item for item in problems)

    graphic = {**ok, "license_name": "original-graphic"}
    problems = require_photographic_assets([ok, graphic, ok, ok], expected_scenes=4)
    assert any("graphic placeholder" in item for item in problems)
    assert any("license" in item.lower() or "not accepted" in item.lower() for item in problems)


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


# ---------------------------------------------------------------------------
# Production wiring: generate-reel / --scheduled use real photo retrieval
# ---------------------------------------------------------------------------

from datetime import datetime, timezone

from app.reels.commands import find_licensed_assets, generate_reel_command
from app.reels.config import ReelConfig
from app.reels.photos import (
    PhotoError,
    build_scene_photo_queries,
    retrieve_licensed_photos_for_script,
)
from app.reels.pipeline import Candidate, run_generation
from app.reels.store import ReelStore


def _story_script(*, title_hint: str = "Kindergeld", scenes: int = 4) -> dict:
    scene_list = [
        {
            "number": index + 1,
            "duration_seconds": 3,
            "narration": f"صحنه {index + 1}",
            "on_screen_text": str(index + 1),
            "visual_prompt": f"{title_hint} scene {index + 1} Germany photograph",
        }
        for index in range(scenes)
    ]
    return {
        "status": "ready",
        "narration": "خبر کوتاه برای خانواده در آلمان.",
        "caption": "خبر",
        "angle": title_hint,
        "storyboard_json": json.dumps({"scenes": scene_list}, ensure_ascii=False),
        "story_package": {"event_id": f"test-{title_hint.lower()}", "scenes": scene_list},
        "fact_pack": {
            "event_summary": f"{title_hint} change for households in Germany",
            "verified_facts": [{"text": f"{title_hint} confirmed for residents"}],
        },
        "voice_estimate_usd": 0.02,
        "reel_id": f"test-{title_hint.lower()}",
    }


def _openverse_transport(jpeg_bytes: bytes, *, mode: str = "ok", jpeg_by_url: dict[str, bytes] | None = None):
    """Serve unique Openverse hits and JPEG bodies. Commons returns empty."""

    import urllib.parse

    counter = {"n": 0}
    jpeg_by_url = jpeg_by_url or {}

    def transport(request, timeout):
        url = request.full_url
        if "api.openverse.org" in url:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q", ["Germany news"])[0]
            if mode == "empty":
                return json.dumps({"results": []}).encode("utf-8")
            if mode == "irrelevant":
                counter["n"] += 1
                n = counter["n"]
                return json.dumps(
                    {
                        "results": [
                            {
                                "title": f"unrelated beach sunset {n}",
                                "url": f"https://live.staticflickr.com/1/irr-{n}.jpg",
                                "foreign_landing_url": f"https://flickr.com/irr-{n}",
                                "creator": f"Tourist{n}",
                                "license": "by",
                                "license_version": "2.0",
                                "license_url": "https://creativecommons.org/licenses/by/2.0/",
                                "provider": "flickr",
                                "width": 1200,
                                "height": 900,
                                "tags": [{"name": "beach"}, {"name": "sunset"}],
                                "description": "Vacation photo",
                            }
                        ]
                    }
                ).encode("utf-8")
            if mode == "missing_license_url":
                counter["n"] += 1
                n = counter["n"]
                return json.dumps(
                    {
                        "results": [
                            {
                                "title": query,
                                "url": f"https://live.staticflickr.com/1/nolurl-{n}.jpg",
                                "foreign_landing_url": f"https://flickr.com/nolurl-{n}",
                                "creator": f"Photographer{n}",
                                "license": "by",
                                "license_version": "2.0",
                                "license_url": "",
                                "provider": "flickr",
                                "width": 1200,
                                "height": 900,
                            }
                        ]
                    }
                ).encode("utf-8")
            if mode == "nc_only":
                counter["n"] += 1
                n = counter["n"]
                return json.dumps(
                    {
                        "results": [
                            {
                                "title": query,
                                "url": f"https://live.staticflickr.com/1/nc-{n}.jpg",
                                "foreign_landing_url": f"https://flickr.com/nc-{n}",
                                "creator": "Restricted",
                                "license": "by-nc",
                                "license_version": "2.0",
                                "license_url": "https://creativecommons.org/licenses/by-nc/2.0/",
                                "provider": "flickr",
                                "width": 1000,
                                "height": 800,
                            }
                        ]
                    }
                ).encode("utf-8")
            counter["n"] += 1
            n = counter["n"]
            tags = [{"name": part} for part in query.split()[:6] if len(part) > 2]
            return json.dumps(
                {
                    "results": [
                        {
                            "title": f"{query} photograph {n}",
                            "url": f"https://live.staticflickr.com/1/ok-{n}.jpg",
                            "foreign_landing_url": f"https://flickr.com/ok-{n}",
                            "creator": f"Photographer{n}",
                            "license": "by",
                            "license_version": "2.0",
                            "license_url": "https://creativecommons.org/licenses/by/2.0/",
                            "provider": "flickr",
                            "width": 1200,
                            "height": 900,
                            "attribution": f"Photographer{n} / CC BY 2.0",
                            "tags": tags,
                            "description": query,
                        }
                    ]
                }
            ).encode("utf-8")
        if "commons.wikimedia.org" in url:
            return json.dumps({"query": {"pages": {}}}).encode("utf-8")
        if mode == "download_fail":
            raise PhotoError("forced download failure")
        if url in jpeg_by_url:
            return jpeg_by_url[url]
        if ".jpg" in url or "staticflickr.com" in url:
            return jpeg_bytes
        raise PhotoError(f"unexpected url {url}")

    return transport


def _reel_config(tmp_path: Path, **overrides) -> ReelConfig:
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
        editorial_rank_provider="off",
        editorial_rank_approved=False,
        editorial_audience_id="iranians_in_germany",
        editorial_min_score=0.55,
        editorial_audiences_file=tmp_path / "editorial_audiences.json",
    )
    base.update(overrides)
    return ReelConfig(**base)


def test_build_scene_photo_queries_are_dynamic_per_topic() -> None:
    kindergeld = build_scene_photo_queries(
        "Kindergeld rises to 259 euro",
        "Families in Germany keep monthly Kindergeld.",
        _story_script(title_hint="Kindergeld", scenes=4),
    )
    ticket = build_scene_photo_queries(
        "Deutschlandticket price 2027",
        "Monthly ticket stays available nationwide.",
        _story_script(title_hint="Deutschlandticket", scenes=3),
    )
    assert len(kindergeld) == 4
    assert len(ticket) == 3
    flat_k = " ".join(q for group in kindergeld for q in group).lower()
    flat_t = " ".join(q for group in ticket for q in group).lower()
    assert "kindergeld" in flat_k
    assert "deutschlandticket" in flat_t
    assert "frühstartrente" not in flat_k and "fruehstart" not in flat_k


def test_missing_storyboard_fails_without_four_scene_fallback() -> None:
    with pytest.raises(PhotoError, match="storyboard is missing|invalid"):
        build_scene_photo_queries(
            "Kindergeld rises",
            "Families in Germany.",
            {"status": "ready", "storyboard_json": "[]", "story_package": {"scenes": []}},
        )


def test_irrelevant_metadata_is_rejected(tmp_path: Path, monkeypatch) -> None:
    jpeg = tmp_path / "seed.jpg"
    _jpeg_bytes(jpeg)
    monkeypatch.setattr("app.reels.photos.time.sleep", lambda *_a, **_k: None)
    with pytest.raises(PhotoError, match="no downloadable licensed photograph"):
        retrieve_licensed_photos_for_script(
            "Kindergeld rises to 259 euro",
            "Families in Germany keep Kindergeld.",
            _story_script(title_hint="Kindergeld", scenes=2),
            tmp_path / "assets-irrelevant",
            transport=_openverse_transport(jpeg.read_bytes(), mode="irrelevant"),
        )


def test_missing_license_url_is_rejected(tmp_path: Path, monkeypatch) -> None:
    jpeg = tmp_path / "seed.jpg"
    _jpeg_bytes(jpeg)
    monkeypatch.setattr("app.reels.photos.time.sleep", lambda *_a, **_k: None)
    with pytest.raises(PhotoError, match="no downloadable licensed photograph"):
        retrieve_licensed_photos_for_script(
            "Kindergeld rises to 259 euro",
            "Families in Germany keep Kindergeld.",
            _story_script(title_hint="Kindergeld", scenes=1),
            tmp_path / "assets-nolurl",
            transport=_openverse_transport(jpeg.read_bytes(), mode="missing_license_url"),
        )


def test_retrieve_licensed_photos_matches_scene_count(tmp_path: Path) -> None:
    jpeg = tmp_path / "seed.jpg"
    _jpeg_bytes(jpeg)
    script = _story_script(title_hint="Bürgergeld", scenes=5)
    assets = retrieve_licensed_photos_for_script(
        "Bürgergeld payment update",
        "Households in Germany receive Bürgergeld support.",
        script,
        tmp_path / "assets",
        transport=_openverse_transport(jpeg.read_bytes()),
        reel_id="buergergeld",
    )
    assert len(assets) == 5
    for index, asset in enumerate(assets):
        assert Path(asset["path"]).is_file()
        assert f"scene-{index + 1:02d}" in Path(asset["path"]).name
        assert asset["license_name"]
        assert asset["author"]
        assert asset["source_url"]
    assert (tmp_path / "assets" / "image_search_log.json").is_file()
    assert (tmp_path / "assets" / "attribution_manifest.json").is_file()


def test_missing_photographs_raise_and_log(tmp_path: Path, monkeypatch) -> None:
    jpeg = tmp_path / "seed.jpg"
    _jpeg_bytes(jpeg)
    monkeypatch.setattr("app.reels.photos.time.sleep", lambda *_a, **_k: None)
    with pytest.raises(PhotoError, match="no downloadable licensed photograph"):
        retrieve_licensed_photos_for_script(
            "Unknown topic",
            "No images available.",
            _story_script(title_hint="Unknown", scenes=2),
            tmp_path / "assets-empty",
            transport=_openverse_transport(jpeg.read_bytes(), mode="empty"),
        )


def test_invalid_licensing_blocks_retrieval(tmp_path: Path, monkeypatch) -> None:
    jpeg = tmp_path / "seed.jpg"
    _jpeg_bytes(jpeg)
    monkeypatch.setattr("app.reels.photos.time.sleep", lambda *_a, **_k: None)
    with pytest.raises(PhotoError, match="no downloadable licensed photograph"):
        retrieve_licensed_photos_for_script(
            "Restricted topic",
            "Only NC licenses.",
            _story_script(title_hint="Restricted", scenes=2),
            tmp_path / "assets-nc",
            transport=_openverse_transport(jpeg.read_bytes(), mode="nc_only"),
        )


def test_download_failure_is_logged(tmp_path: Path, monkeypatch) -> None:
    jpeg = tmp_path / "seed.jpg"
    _jpeg_bytes(jpeg)
    dest = tmp_path / "assets-fail"
    monkeypatch.setattr("app.reels.photos.time.sleep", lambda *_a, **_k: None)
    with pytest.raises(PhotoError, match="no downloadable licensed photograph|download"):
        retrieve_licensed_photos_for_script(
            "Download fail topic",
            "Images cannot be fetched.",
            _story_script(title_hint="Fail", scenes=1),
            dest,
            transport=_openverse_transport(jpeg.read_bytes(), mode="download_fail"),
        )
    assert not (dest / "scene-01.jpg").is_file()


def test_find_licensed_assets_uses_photo_service(tmp_path: Path) -> None:
    jpeg = tmp_path / "seed.jpg"
    _jpeg_bytes(jpeg)
    config = _reel_config(tmp_path)
    candidate = Candidate(
        title="Mindestlohn rises in Germany",
        summary="The federal minimum wage increase affects workers.",
        url="https://example.com/mindestlohn",
        publisher="Tagesschau",
        published_at=datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc),
        category="work",
    )
    assets = find_licensed_assets(
        candidate,
        _story_script(title_hint="Mindestlohn", scenes=4),
        config=config,
        transport=_openverse_transport(jpeg.read_bytes()),
    )
    assert len(assets) == 4
    assert all(asset.get("kind") == "licensed-photo" for asset in assets)
    assert all(Path(asset["path"]).is_file() for asset in assets)
    assert not any("remotion-graphic" in str(asset.get("license_name")) for asset in assets)


def test_pipeline_missing_photos_fail_before_tts(tmp_path: Path) -> None:
    config = _reel_config(tmp_path, paid_generation=True, elevenlabs_approved=True)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Kindergeld rises to 259 euro in 2026",
        summary="The federal government confirmed Kindergeld rises.",
        url="https://example.com/kindergeld-photos-fail",
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )
    voice_calls: list[str] = []

    def narrate(text, voice_id):
        voice_calls.append(text)
        raise AssertionError("ElevenLabs must not run without photographs")

    result = run_generation(
        config,
        store,
        now=now,
        scheduled=False,
        candidates=[candidate],
        verify_source=lambda item: {"ok": True, "excerpt": item.summary},
        write_script=lambda candidate, checked, paid_generation: _story_script(),
        find_assets=lambda candidate, script: (_ for _ in ()).throw(PhotoError("no downloadable licensed photograph")),
        narrate=narrate,
        render_video=lambda *a, **k: (_ for _ in ()).throw(AssertionError("render")),
        probe_video=lambda path: (_ for _ in ()).throw(AssertionError("probe")),
    )
    assert result.status == "failed"
    assert "photograph" in result.message.lower() or "no downloadable" in result.message.lower()
    assert voice_calls == []
    reel = store.get(result.reel_id)
    assert reel is not None
    assert reel["local_status"] == "failed"
    assert reel["local_status"] not in {"qa_passed", "queued"}


def test_pipeline_graphic_placeholder_blocks_before_tts(tmp_path: Path) -> None:
    config = _reel_config(tmp_path, paid_generation=True)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Kindergeld rises",
        summary="Confirmed rise.",
        url="https://example.com/kindergeld-graphic",
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )
    voice_calls: list[str] = []
    result = run_generation(
        config,
        store,
        now=now,
        scheduled=False,
        candidates=[candidate],
        verify_source=lambda item: {"ok": True, "excerpt": item.summary},
        write_script=lambda candidate, checked, paid_generation: _story_script(),
        find_assets=lambda candidate, script: [
            {
                "path": "",
                "license_name": "remotion-graphic",
                "kind": "remotion-graphic",
                "author": "",
                "source_url": "",
                "role": "remotion-graphic",
            }
        ],
        narrate=lambda text, voice_id: voice_calls.append(text) or {},
        render_video=lambda *a, **k: {},
        probe_video=lambda path: {},
    )
    assert result.status == "failed"
    assert "mandatory photographs" in result.message
    assert voice_calls == []


def test_manual_and_scheduled_generation_retrieve_photographs(tmp_path: Path, monkeypatch) -> None:
    """Both generate-reel and generate-reel --scheduled call find_licensed_assets."""

    jpeg = tmp_path / "seed.jpg"
    _jpeg_bytes(jpeg)
    jpeg_bytes = jpeg.read_bytes()
    config = _reel_config(tmp_path, paid_generation=False)
    store = ReelStore(config.database_path)
    store.migrate()
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Elterngeld rules update",
        summary="Parents in Germany receive clarified Elterngeld guidance.",
        url="https://example.com/elterngeld-photos",
        publisher="BMFSFJ",
        published_at=now,
        category="family",
    )

    monkeypatch.setenv("REEL_WORKING_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("REEL_DATABASE_PATH", str(config.database_path))
    monkeypatch.setenv("REEL_OUTBOX_DIR", str(config.outbox_dir))
    monkeypatch.setenv("REEL_LOCK_PATH", str(config.lock_path))
    monkeypatch.setenv("REEL_LOG_PATH", str(config.log_path))
    monkeypatch.setenv("REEL_PAID_GENERATION", "false")
    monkeypatch.setenv("REEL_TARGET_PAGE", "almanyar")

    captured: dict = {"find_calls": 0, "assets": None}

    def fake_find(candidate_arg, script, *, config=None, transport=None):
        captured["find_calls"] += 1
        assets = find_licensed_assets(
            candidate_arg,
            script,
            config=config or _reel_config(tmp_path),
            transport=_openverse_transport(jpeg_bytes),
        )
        captured["assets"] = assets
        return assets

    monkeypatch.setattr("app.reels.commands.discover_candidates", lambda cfg, moment: [candidate])
    monkeypatch.setattr("app.reels.commands.verify_http", lambda item: {"ok": True, "excerpt": item.summary})
    monkeypatch.setattr(
        "app.reels.commands.write_grounded_script",
        lambda candidate, checked, paid_generation=False, **kwargs: _story_script(title_hint="Elterngeld"),
    )
    monkeypatch.setattr(
        "app.reels.commands.find_licensed_assets",
        fake_find,
    )
    # Prevent narrate/render from being reached; paid_generation is false so blocked_paid after photos.
    monkeypatch.setattr("app.reels.commands.load_reel_config", lambda: _reel_config(tmp_path))

    code = generate_reel_command(scheduled=False, target="almanyar", now=now)
    assert code == 0
    assert captured["find_calls"] == 1
    assert captured["assets"] and len(captured["assets"]) == 4
    assert all(Path(a["path"]).is_file() for a in captured["assets"])

    # Second story for scheduled path so select_story is not blocked as duplicate.
    candidate2 = Candidate(
        title="Wohngeld reform briefing",
        summary="Housing benefit changes for tenants in Germany.",
        url="https://example.com/wohngeld-photos",
        publisher="BMI",
        published_at=now,
        category="housing",
    )
    monkeypatch.setattr("app.reels.commands.discover_candidates", lambda cfg, moment: [candidate2])
    monkeypatch.setattr(
        "app.reels.commands.write_grounded_script",
        lambda candidate, checked, paid_generation=False, **kwargs: _story_script(title_hint="Wohngeld"),
    )
    code = generate_reel_command(scheduled=False, target="almanyar", now=now)
    # scheduled=False again is fine for wiring; also exercise scheduled=True below
    assert code == 0
    assert captured["find_calls"] == 2

    candidate3 = Candidate(
        title="Kindergeld payment calendar update",
        summary="Families in Germany receive Kindergeld on the confirmed monthly schedule.",
        url="https://example.com/kindergeld-scheduled-photos",
        publisher="Familienkasse",
        published_at=now,
        category="family",
    )
    monkeypatch.setattr("app.reels.commands.discover_candidates", lambda cfg, moment: [candidate3])
    monkeypatch.setattr(
        "app.reels.commands.write_grounded_script",
        lambda candidate, checked, paid_generation=False, **kwargs: _story_script(title_hint="Kindergeld"),
    )
    code = generate_reel_command(scheduled=True, target="almanyar", now=now)
    assert code == 0
    assert captured["find_calls"] == 3
    assert all(Path(a["path"]).is_file() for a in captured["assets"])


def test_acceptance_production_path_mocked_providers(tmp_path: Path) -> None:
    """Full path: script → photos → (mocked) Aran → Remotion → QA. No live paid calls."""

    jpeg = tmp_path / "seed.jpg"
    _jpeg_bytes(jpeg)
    config = _reel_config(
        tmp_path,
        paid_generation=True,
        elevenlabs_approved=True,
        per_reel_max_usd=1.0,
    )
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Kindergeld rises to 259 euro in 2026",
        summary="The federal government confirmed Kindergeld rises to 259 euro per child from January 2026 for families in Germany.",
        url="https://example.com/kindergeld-acceptance",
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )
    tts_calls: list[str] = []
    video_path = tmp_path / "out" / "reel.mp4"
    video_path.parent.mkdir(parents=True)

    def find_assets(candidate_arg, script):
        return find_licensed_assets(
            candidate_arg,
            script,
            config=config,
            transport=_openverse_transport(jpeg.read_bytes()),
        )

    def narrate(text, voice_id):
        tts_calls.append(text)
        audio = tmp_path / "audio" / "aran.mp3"
        audio.parent.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"ID3" + b"\x00" * 2048)
        return {
            "path": str(audio),
            "provider": "elevenlabs",
            "voice_id": voice_id,
            "model_id": "eleven_v4",
            "duration_seconds": 12.0,
            "characters": len(text),
            "usd": 0.02,
        }

    def render_video(script, assets, audio):
        assert len(assets) == 4
        assert all(Path(a["path"]).is_file() for a in assets)
        assert all(a.get("license_name") not in {"remotion-graphic", "original-graphic"} for a in assets)
        # Keep index alignment: scene file names match order.
        for index, asset in enumerate(assets):
            assert f"scene-{index + 1:02d}" in Path(asset["path"]).name
        video_path.write_bytes(b"\x00" * 64)
        return {"path": str(video_path)}

    def probe_video(path):
        return {
            "width": 1080,
            "height": 1920,
            "video_codec": "h264",
            "has_audio": True,
            "duration_seconds": 12.0,
            "audio_duration_seconds": 12.0,
            "checksum_sha256": "abc",
        }

    result = run_generation(
        config,
        store,
        now=now,
        scheduled=True,
        candidates=[candidate],
        verify_source=lambda item: {"ok": True, "excerpt": item.summary},
        write_script=lambda candidate, checked, paid_generation: _story_script(title_hint="Kindergeld"),
        find_assets=find_assets,
        narrate=narrate,
        render_video=render_video,
        probe_video=probe_video,
    )
    assert result.status == "qa_passed"
    assert tts_calls, "TTS should run only after photos succeed"
    reel = store.get(result.reel_id)
    assert reel["local_status"] == "qa_passed"
    assets_dir = tmp_path / "storage" / "generated" / "reels" / "assets"
    photo_files = list(assets_dir.rglob("scene-*.jpg"))
    assert len(photo_files) >= 4


def test_photo_failure_never_queues_or_calls_tts(tmp_path: Path, monkeypatch) -> None:
    config = _reel_config(tmp_path, paid_generation=True, elevenlabs_approved=True)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = Candidate(
        title="Kindergeld rises to 259 euro in 2026",
        summary="The federal government confirmed Kindergeld rises for families in Germany.",
        url="https://example.com/kindergeld-no-queue",
        publisher="Bundesregierung",
        published_at=now,
        category="family",
    )
    monkeypatch.setattr("app.reels.commands.load_reel_config", lambda: config)
    monkeypatch.setattr("app.reels.commands.discover_candidates", lambda cfg, moment: [candidate])
    monkeypatch.setattr("app.reels.commands.verify_http", lambda item: {"ok": True, "excerpt": item.summary})
    monkeypatch.setattr(
        "app.reels.commands.write_grounded_script",
        lambda candidate, checked, paid_generation=False, **kwargs: _story_script(title_hint="Kindergeld"),
    )
    monkeypatch.setattr(
        "app.reels.commands.find_licensed_assets",
        lambda candidate, script, **kwargs: (_ for _ in ()).throw(PhotoError("no downloadable licensed photograph")),
    )
    tts_calls: list[str] = []
    monkeypatch.setattr(
        "app.reels.commands.narrate_aran",
        lambda *a, **k: tts_calls.append("tts") or {},
    )
    packages: list[str] = []
    monkeypatch.setattr(
        "app.reels.commands.write_package",
        lambda *a, **k: packages.append("packaged"),
    )
    code = generate_reel_command(scheduled=False, target="almanyar", now=now)
    assert code == 1
    assert tts_calls == []
    assert packages == []
    store = ReelStore(config.database_path)
    rows = store.recent_reels() if hasattr(store, "recent_reels") else []
    # Inspect latest attempt status via cron log / reel rows.
    with store.connect() as connection:
        statuses = [row[0] for row in connection.execute("SELECT local_status FROM reels")]
        cron = [row[0] for row in connection.execute("SELECT status FROM cron_job_logs")]
    assert "qa_passed" not in statuses
    assert "queued" not in statuses
    assert "queued" not in cron
    assert any(status == "failed" for status in statuses)


def test_realistic_photo_remotion_integration(tmp_path: Path, monkeypatch) -> None:
    """Existing story + saved Aran audio + mocked search of real local photos → real Remotion."""

    import hashlib
    import shutil

    import app.reels.render as render_mod
    from app.reels.qa import technical_qa_report, write_contact_sheet

    source = Path("storage/generated/pilot/first-live-news-20261121-125501")
    photo_bank = Path("storage/generated/pilot/first-live-news-20261121-125501-photos/assets")
    story_path = source / "story_package.json"
    audio_path = source / "audio" / "narration.mp3"
    if not story_path.is_file() or not audio_path.is_file():
        pytest.skip("live pilot story/audio fixtures are not present")
    local_photos = [photo_bank / f"scene-{index:02d}.jpg" for index in range(1, 5)]
    if not all(path.is_file() for path in local_photos):
        pytest.skip("local licensed photograph fixtures are not present")

    story = json.loads(story_path.read_text(encoding="utf-8"))
    # Replace graphic-instruction prompts with concrete English search subjects.
    prompts = [
        "Bundesrat Berlin government building exterior",
        "euro coins close up savings",
        "pink piggy bank coins savings",
        "retirement bankbook documents desk",
    ]
    for index, scene in enumerate(story["scenes"]):
        scene["visual_prompt"] = prompts[index]

    fact_pack = {}
    fact_path = source / "fact_pack.json"
    if fact_path.is_file():
        fact_pack = json.loads(fact_path.read_text(encoding="utf-8"))

    # Remotion serves images from the project public/ tree; do not redirect PUBLIC.
    monkeypatch.setattr("app.reels.photos.time.sleep", lambda *_a, **_k: None)
    run_id = f"photo-int-{tmp_path.name}"
    stage_dir = render_mod.PUBLIC / "runtime" / run_id
    if stage_dir.exists():
        shutil.rmtree(stage_dir)

    jpeg_by_url: dict[str, bytes] = {}
    counter = {"n": 0}

    def transport(request, timeout):
        import urllib.parse

        url = request.full_url
        if "api.openverse.org" in url:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q", ["Germany"])[0]
            counter["n"] += 1
            n = counter["n"]
            photo_bytes = local_photos[(n - 1) % 4].read_bytes()
            download = f"https://live.staticflickr.com/1/live-{n}.jpg"
            jpeg_by_url[download] = photo_bytes
            return json.dumps(
                {
                    "results": [
                        {
                            "title": query,
                            "url": download,
                            "foreign_landing_url": f"https://flickr.com/live-{n}",
                            "creator": f"FixturePhotographer{n}",
                            "license": "by",
                            "license_version": "2.0",
                            "license_url": "https://creativecommons.org/licenses/by/2.0/",
                            "provider": "flickr",
                            "width": 1600,
                            "height": 1200,
                            "attribution": f"FixturePhotographer{n} / CC BY 2.0",
                            "tags": [{"name": part} for part in query.split()[:6]],
                            "description": query,
                        }
                    ]
                }
            ).encode("utf-8")
        if "commons.wikimedia.org" in url:
            return json.dumps({"query": {"pages": {}}}).encode("utf-8")
        if url in jpeg_by_url:
            return jpeg_by_url[url]
        raise PhotoError(f"unexpected url {url}")

    tts_calls: list[str] = []
    monkeypatch.setattr(
        "app.reels.pilot.narrate_persian",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError(tts_calls.append("tts") or "TTS must not run")),
    )

    out_dir = tmp_path / "photo-integration"
    try:
        assets = retrieve_licensed_photos_for_script(
            "Bundesrat approves Fruehstartrente early start pension",
            "Eligible children in Germany receive 10 euro monthly retirement savings contributions.",
            {"story_package": story, "fact_pack": fact_pack},
            out_dir / "assets",
            transport=transport,
            reel_id=run_id,
        )
        assert len(assets) == 4
        assert all(Path(asset["path"]).is_file() for asset in assets)
        assert all(asset.get("license_url") for asset in assets)

        # Preserve saved Aran narration without copying onto itself issues.
        audio_dir = out_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        reused_audio = audio_dir / "narration.mp3"
        shutil.copy2(audio_path, reused_audio)

        result = run_persian_reel_pilot(
            out_dir=out_dir,
            run_id=run_id,
            story_package=story,
            audio_path=reused_audio,
            assets=assets,
            require_live_voice=False,
            overwrite=True,
            database_path=out_dir / "pilot.sqlite3",
        )
        assert tts_calls == []
        assert result.status == "qa_passed", f"{result.status}: {result.message} detail={result.detail}"
        assert Path(result.video_path).is_file()
        assert Path(result.contact_sheet_path).is_file()
        assert Path(result.qa_report_path).is_file()

        props_path = stage_dir / "props.json"
        assert props_path.is_file()
        props = json.loads(props_path.read_text(encoding="utf-8"))
        staged = props.get("scenes") or []
        assert len(staged) == 4
        assert all(scene.get("graphic") is False for scene in staged)
        assert all(scene.get("image") for scene in staged)

        # Confirm Remotion staged bytes match the downloaded photographs (not graphic plates).
        for index, scene in enumerate(staged):
            staged_file = render_mod.PUBLIC / scene["image"]
            assert staged_file.is_file()
            downloaded = Path(assets[index]["path"]).read_bytes()
            assert hashlib.sha256(staged_file.read_bytes()).hexdigest() == hashlib.sha256(downloaded).hexdigest()

        qa = technical_qa_report(
            Path(result.video_path),
            contact_sheet=out_dir / "contact-sheet-verify.jpg",
            narration=Path(result.narration_path).read_text(encoding="utf-8"),
            require_audible_audio=True,
        )
        (out_dir / "qa_technical_verify.json").write_text(
            json.dumps(qa, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        assert qa.get("technical_pass") is True
        write_contact_sheet(Path(result.video_path), out_dir / "contact-sheet-final.jpg", frames=4)
        assert (out_dir / "contact-sheet-final.jpg").is_file()
    finally:
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
