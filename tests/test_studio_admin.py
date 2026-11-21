"""The admin reads the same SQLite file the generator writes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.reels.store import ReelStore


def _news_schema(path: Path) -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "database" / "migrations"
    connection = sqlite3.connect(path)
    for name in ("001_initial.sql", "002_selection_history.sql"):
        connection.executescript((root / name).read_text(encoding="utf-8"))
    connection.execute(
        "INSERT INTO clients (id, name, timezone, daily_reel_limit, created_at) VALUES ('default', 'Default', 'Europe/Berlin', 3, '2026-01-01T00:00:00+00:00')"
    )
    connection.execute(
        """
        INSERT INTO news_events (
            id, client_id, event_fingerprint, block_key, title, normalized_title, title_fingerprint,
            first_discovered_at, state
        ) VALUES ('event-1', 'default', 'fp', 'block', 'Kindergeld rises', 'kindergeld rises', 'fp1',
                  '2026-11-19T00:00:00+00:00', 'DISCOVERED')
        """
    )
    connection.commit()
    connection.close()


def test_admin_lists_news_and_reels_from_one_database(tmp_path, monkeypatch) -> None:
    database = tmp_path / "news_reels.db"
    _news_schema(database)
    store = ReelStore(database)
    store.migrate()
    from datetime import datetime, timezone

    now = datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc)
    store.upsert_reel(
        {
            "reel_id": "reel-1",
            "story_fingerprint": "fp",
            "target_page": "almanyar",
            "title": "Kindergeld rises",
            "category": "benefits",
            "affected_audience": "parents",
            "editorial_angle": "the payment changed",
            "narration_fa": "",
            "caption_fa": "کپشن",
            "storyboard_json": "{}",
            "video_path": "storage/reel.mp4",
            "duration_seconds": 20,
            "width": 1080,
            "height": 1920,
            "checksum_sha256": "abc",
            "local_status": "ready",
            "production_delivery_id": None,
            "scheduled_for": None,
            "facts_checked_at": now.isoformat(),
            "generation_started_at": now.isoformat(),
            "generation_finished_at": now.isoformat(),
            "error_message": "",
            "retry_count": 0,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    )
    page_id = store.ensure_page("almanyar", username="almanyar", now=now)
    store.upsert_post(
        page_id=page_id,
        reel_id="reel-1",
        title="Kindergeld rises",
        description="کپشن",
        status="ready",
        scheduled_for=None,
        now=now,
    )
    store.add_cron_log(job_name="generate_reel", status="success", message="reel-1", now=now)

    monkeypatch.setenv("STUDIO_DATABASE", str(database))
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "studio.settings")
    import django
    from django.conf import settings

    if not settings.configured:
        django.setup()
    settings.DATABASES["default"]["NAME"] = str(database)
    from django.contrib.auth import get_user_model
    from django.db import connections
    from django.test import Client

    connections.close_all()
    from django.core.management import call_command

    call_command("migrate", run_syncdb=True, verbosity=0)
    user_model = get_user_model()
    if not user_model.objects.filter(username="editor").exists():
        user_model.objects.create_superuser("editor", "editor@localhost", "editor-pass-123")
    client = Client()
    assert client.login(username="editor", password="editor-pass-123")
    for path in ("/", "/library/newsevent/", "/library/post/", "/library/reel/", "/library/cronjoblog/"):
        response = client.get(path)
        assert response.status_code == 200, path
    listed = client.get("/library/post/")
    assert "Kindergeld rises" in listed.content.decode()
    assert "almanyar" in listed.content.decode()
