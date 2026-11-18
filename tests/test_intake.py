"""Discovery intake and concurrent selection."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.database.models import SelectionCandidate
from app.database.repository import NewsReelsRepository
from app.schemas.news import DiscoveredArticle
from app.services.news.intake import run_intake
from app.services.news.sources import configured_news_sources
from tests.support import NOW, event_input

ROOT = Path(__file__).resolve().parents[1]


class ListSource:
    def __init__(self, articles: list[DiscoveredArticle]) -> None:
        self.articles = articles

    def fetch(self, *, window_start: datetime, window_end: datetime):
        from app.schemas.workflow import ResearchResult

        kept = [
            article
            for article in self.articles
            if article.published_at is not None and window_start <= article.published_at <= window_end
        ]
        return ResearchResult(articles=kept)


def _article(title: str, url: str, source: str, published: datetime, language: str = "en") -> DiscoveredArticle:
    return DiscoveredArticle(
        source_name=source,
        source_url=url,
        canonical_url=url,
        title=title,
        summary=title,
        published_at=published,
        language=language,
    )


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    data: dict[str, object] = {
        "database_path": tmp_path / "news.db",
        "output_dir": tmp_path / "media",
        "news_provider": "rss",
        "stopwords_dir": ROOT / "config" / "stopwords",
        "entity_aliases_file": ROOT / "config" / "entity_aliases.example.json",
    }
    data.update(overrides)
    return Settings(_env_file=None, **data)


def _counts(path: Path) -> tuple[int, int]:
    connection = sqlite3.connect(path)
    try:
        content = connection.execute("SELECT COUNT(*) FROM generated_content").fetchone()[0]
        production = connection.execute("SELECT COUNT(*) FROM daily_production").fetchone()[0]
    finally:
        connection.close()
    return int(content), int(production)


def test_intake_fills_incrementally_and_does_not_start_production(tmp_path: Path) -> None:
    repository = NewsReelsRepository(tmp_path / "news.db")
    repository.initialize(client_id="default", name="Default", timezone_name="Europe/Berlin", daily_reel_limit=3, now=NOW)
    settings = _settings(tmp_path)
    first_story = _article(
        "Parliament election in France",
        "https://example.com/france",
        "Example English",
        NOW - timedelta(hours=1),
    )
    later = [
        first_story,
        _article("Court ruling in Italy", "https://example.com/italy", "Example English", NOW - timedelta(hours=1)),
        _article("Sanctions decision in Canada", "https://example.com/canada", "Example English", NOW - timedelta(hours=1)),
    ]
    first = run_intake(settings, repository, now=NOW, source=ListSource([first_story]))
    assert [row.rank for row in first.selections] == [1]
    assert first.limitation is not None
    assert "not reliable multilingual deduplication" in first.limitation
    second = run_intake(settings, repository, now=NOW + timedelta(hours=1), source=ListSource(later))
    assert [row.rank for row in second.selections] == [1, 2, 3]
    assert second.selections[0].id == first.selections[0].id
    assert second.selections[0].created_at == first.selections[0].created_at
    assert _counts(repository.path) == (0, 0)
    assert {event.state for event in repository.list_events("default")} == {"DISCOVERED"}


def test_intake_clusters_the_entity_and_number_hint(tmp_path: Path) -> None:
    repository = NewsReelsRepository(tmp_path / "news.db")
    repository.initialize(client_id="default", name="Default", timezone_name="Europe/Berlin", daily_reel_limit=3, now=NOW)
    settings = _settings(tmp_path)
    articles = [
        _article("ECB holds rates at 4.5 percent", "https://example.com/en", "English", NOW - timedelta(hours=1), "en"),
        _article("EZB belässt Leitzins bei 4,5 Prozent", "https://example.com/de", "German", NOW - timedelta(hours=1), "de"),
    ]
    run_intake(settings, repository, now=NOW, source=ListSource(articles))
    assert len(repository.list_events("default")) == 1
    assert _counts(repository.path) == (0, 0)


def test_missing_sources_fail_without_a_built_in_list(tmp_path: Path) -> None:
    repository = NewsReelsRepository(tmp_path / "news.db")
    repository.initialize(client_id="default", name="Default", timezone_name="Europe/Berlin", daily_reel_limit=3, now=NOW)
    settings = _settings(tmp_path, news_sources=())
    with pytest.raises(ConfigurationError):
        run_intake(settings, repository, now=NOW)
    missing = tmp_path / "missing.json"
    file_settings = _settings(tmp_path, news_sources_file=missing)
    with pytest.raises(ConfigurationError):
        configured_news_sources(file_settings)


def test_two_connections_select_each_event_once(tmp_path: Path) -> None:
    path = tmp_path / "shared.db"
    parent = NewsReelsRepository(path)
    parent.initialize(client_id="default", name="Default", timezone_name="Europe/Berlin", daily_reel_limit=3, now=NOW)
    identifiers = []
    for index in range(5):
        event = parent.insert_event(
            event_input(event_fingerprint=f"thread-{index}", title_fingerprint=f"thread-title-{index}"),
            now=NOW,
        )
        identifiers.append(event.id)
    candidates = [SelectionCandidate(event_id, 0.8, "major") for event_id in identifiers]
    errors: list[BaseException] = []

    def fill() -> None:
        try:
            NewsReelsRepository(path).fill_daily_selections(
                client_id="default",
                production_date="2026-11-18",
                limit=3,
                candidates=candidates,
                now=NOW,
            )
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    from threading import Thread

    threads = [Thread(target=fill) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    rows = parent.list_daily_selections("default", "2026-11-18")
    assert [row.rank for row in rows] == [1, 2, 3]
    assert len({row.event_id for row in rows}) == 3


def test_two_processes_select_each_event_once(tmp_path: Path) -> None:
    path = tmp_path / "processes.db"
    parent = NewsReelsRepository(path)
    parent.initialize(client_id="default", name="Default", timezone_name="Europe/Berlin", daily_reel_limit=3, now=NOW)
    identifiers = []
    for index in range(5):
        event = parent.insert_event(
            event_input(event_fingerprint=f"process-{index}", title_fingerprint=f"process-title-{index}"),
            now=NOW,
        )
        identifiers.append(event.id)
    worker = """
import sys
from datetime import datetime, timezone
from app.database.models import SelectionCandidate
from app.database.repository import NewsReelsRepository
path, raw_ids = sys.argv[1], sys.argv[2].split(",")
candidates = [SelectionCandidate(event_id, 0.8, "major") for event_id in raw_ids]
NewsReelsRepository(path).fill_daily_selections(
    client_id="default",
    production_date="2026-11-18",
    limit=3,
    candidates=candidates,
    now=datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc),
)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", worker, str(path), ",".join(identifiers)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    outputs = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0, 0], outputs
    checker = NewsReelsRepository(path)
    rows = checker.list_daily_selections("default", "2026-11-18")
    assert [row.rank for row in rows] == [1, 2, 3]
    assert len({row.event_id for row in rows}) == 3
    assert _counts(path) == (0, 0)
