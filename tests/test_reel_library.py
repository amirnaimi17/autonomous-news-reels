"""Local Reel library: posts, videos, cron history, and one-at-a-time generation."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.reels.catalog import import_library
from app.reels.config import ReelConfig
from app.reels.cron import RunLock, cron_block, install_cron_text, remove_cron_text
from app.reels.pipeline import Candidate, run_generation, slot_decision
from app.reels.store import ReelStore


def _config(tmp_path) -> ReelConfig:
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


def _candidate(title: str, url: str, when: datetime) -> Candidate:
    return Candidate(title=title, summary="A household change for residents in Germany.", url=url, publisher="Tagesschau", published_at=when, category="transport")


def _run(config, store, candidates, now, **overrides):
    defaults = dict(
        verify_source=lambda candidate: {"ok": True, "excerpt": candidate.title},
        write_script=lambda candidate, checked, paid_generation: {"status": "blocked_paid", "message": "paid generation is disabled"},
        find_assets=lambda candidate, script: [],
        narrate=lambda text, voice_id: {},
        render_video=lambda script, assets, audio: {},
        probe_video=lambda path: {},
    )
    defaults.update(overrides)
    return run_generation(config, store, now=now, scheduled=False, candidates=candidates, **defaults)


def test_schema_tracks_posts_videos_and_cron(tmp_path) -> None:
    store = ReelStore(tmp_path / "reels.sqlite3")
    store.migrate()
    with store.connect() as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"reels", "posts", "post_videos", "cron_job_logs", "pages"}.issubset(names)


def test_library_import_is_idempotent(tmp_path) -> None:
    video = tmp_path / "preview_reel.mp4"
    folder = tmp_path / "visual"
    folder.mkdir()
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=4",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            str(video),
        ],
        check=True,
        capture_output=True,
    )
    video_in_folder = folder / "preview_reel.mp4"
    video_in_folder.write_bytes(video.read_bytes())
    (folder / "proposed_caption.txt").write_text("caption", encoding="utf-8")
    entry = {
        "reel_id": "sample-reel",
        "fingerprint": "sample-fingerprint",
        "folder": folder,
        "video_name": "preview_reel.mp4",
        "caption_name": "proposed_caption.txt",
        "title": "Sample",
        "angle": "A checked household change.",
        "audience": "Iranians living in Germany",
        "category": "transport",
        "post_status": "ready",
        "video_status": "ready",
        "facts_checked_at": "2026-11-19T19:00:00+00:00",
        "audio": tmp_path / "missing.mp3",
        "package": False,
    }
    store = ReelStore(tmp_path / "reels.sqlite3")
    assert import_library(store, entries=(entry,)) == ["sample-reel"]
    assert import_library(store, entries=(entry,)) == ["sample-reel"]
    assert len(store.recent_posts()) == 1
    post = store.recent_posts()[0]
    assert post["page_name"] == "almanyar"
    assert post["status"] == "ready"
    assert len(store.videos_for(post["id"])) == 1
    assert store.videos_for(post["id"])[0]["width"] == 1080


def test_irrelevant_stale_and_duplicate_stories_are_recorded(tmp_path) -> None:
    config = _config(tmp_path)
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    irrelevant = _candidate("Markets rally on Wall Street", "https://example.com/markets", now)
    result = _run(config, store, [irrelevant], now)
    assert result.status == "rejected"
    assert result.message == "irrelevant"

    stale = _candidate("Kindergeld rises", "https://example.com/kindergeld", datetime(2026, 10, 1, tzinfo=timezone.utc))
    result = _run(config, store, [stale], now)
    assert result.message == "stale"

    fresh = _candidate("Kindergeld rises again", "https://example.com/kindergeld-2", now)
    results = [_run(config, store, [fresh], now) for _ in range(5)]
    assert results[0].status == "blocked_paid"
    assert results[-1].message == "duplicate"


def _licensed_photo_assets(tmp_path, count: int = 4) -> list[dict]:
    assets = []
    for index in range(count):
        path = tmp_path / f"licensed-{index}.jpg"
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
                "source_url": f"https://example.org/photo/{index}",
                "author": f"Author{index}",
                "license_name": "CC BY 2.0",
                "license_url": "https://creativecommons.org/licenses/by/2.0/",
                "kind": "licensed-photo",
                "role": "scene",
            }
        )
    return assets


def test_paid_generation_stops_at_the_cost_limit(tmp_path) -> None:
    config = _config(tmp_path)
    config = ReelConfig(**{**config.__dict__, "paid_generation": True, "per_reel_max_usd": 0.50})
    store = ReelStore(config.database_path)
    now = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
    candidate = _candidate("Kindergeld payment date", "https://example.com/kindergeld-date", now)
    photos = _licensed_photo_assets(tmp_path)

    def script(candidate, checked, paid_generation):
        return {"status": "ready", "narration": "خبر", "caption": "خبر", "voice_estimate_usd": 0.80, "storyboard_json": "{}"}

    result = _run(config, store, [candidate], now, write_script=script, find_assets=lambda candidate, script: photos)
    assert result.status == "rejected"
    assert result.message == "cost limit"


def test_missed_berlin_slot_is_not_caught_up(tmp_path) -> None:
    config = _config(tmp_path)
    winter = datetime(2026, 1, 19, 6, 40, tzinfo=timezone.utc)
    assert winter.astimezone(ZoneInfo("Europe/Berlin")).hour == 7
    assert slot_decision(winter, config, scheduled=True) == "missed_slot"
    on_time = datetime(2026, 1, 19, 6, 0, tzinfo=timezone.utc)
    assert slot_decision(on_time, config, scheduled=True) == "ok"
    summer = datetime(2026, 7, 19, 5, 0, tzinfo=timezone.utc)
    assert summer.astimezone(ZoneInfo("Europe/Berlin")).hour == 7
    assert slot_decision(summer, config, scheduled=True) == "ok"
    after_clock_change = datetime(2026, 10, 25, 6, 0, tzinfo=timezone.utc)
    assert after_clock_change.astimezone(ZoneInfo("Europe/Berlin")).strftime("%H:%M") == "07:00"


def test_django_crontab_uses_the_four_berlin_hours() -> None:
    from studio.settings import CRONJOBS, CRONTAB_LOCK_JOBS

    assert CRONTAB_LOCK_JOBS is True
    assert CRONJOBS == [("0 7,11,15,19 * * *", "library.cron.generate_scheduled_reel")]


def test_cron_block_uses_the_python_lock_without_external_flock(tmp_path) -> None:
    config = _config(tmp_path)
    block = cron_block(config)
    assert "CRON_TZ=Europe/Berlin" in block
    assert "0 7,11,15,19 * * *" in block
    # generate_reel_command acquires RunLock itself. An outer flock on the
    # same file would prevent the Python command from acquiring that lock.
    assert "flock -n" not in block
    assert f"cd {tmp_path.resolve()} && /usr/bin/python3 -m app.cli generate-reel" in block
    assert "generate-reel --target almanyar --scheduled" in block
    installed = install_cron_text("0 9 * * * echo keep\n", config)
    assert "echo keep" in installed
    assert installed.count("BEGIN autonomous-news-reels") == 1
    assert "BEGIN autonomous-news-reels" not in remove_cron_text(installed)


def test_overlapping_runs_do_not_both_hold_the_lock(tmp_path) -> None:
    path = tmp_path / "reels.lock"
    first = RunLock(path)
    second = RunLock(path)
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()
