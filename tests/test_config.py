"""Configuration and calendar rules."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.time import FixedClock, production_date


def test_defaults_match_the_berlin_schedule() -> None:
    settings = Settings(_env_file=None)
    assert settings.timezone == "Europe/Berlin"
    assert settings.production_slots == ("09:00", "14:00", "19:00")
    assert settings.daily_reel_limit == 3
    assert settings.news_window_hours == 72
    assert settings.fail_closed_deduplication is True
    assert settings.instagram_publish_enabled is False
    assert settings.slot_limit == 3
    assert len(settings.news_sources) == 5


def test_slots_are_sorted_and_duplicates_are_rejected() -> None:
    settings = Settings(_env_file=None, production_slots="19:00, 09:00")
    assert settings.production_slots == ("09:00", "19:00")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, production_slots="09:00,09:00")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, production_slots="25:00")


def test_news_sources_accept_json_and_csv() -> None:
    parsed = Settings(
        _env_file=None,
        news_sources='[{"name":"Local","url":"https://example.com/rss.xml"}]',
    )
    assert parsed.news_sources[0].name == "Local"
    listed = Settings(_env_file=None, news_sources="https://example.com/a.xml,https://example.com/b.xml")
    assert [source.url for source in listed.news_sources] == [
        "https://example.com/a.xml",
        "https://example.com/b.xml",
    ]


def test_invalid_timezone_and_odd_resolution_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, timezone="Mars/Olympus")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, video_width=1081)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, client_id="Default")


def test_secrets_are_masked() -> None:
    settings = Settings(_env_file=None, telegram_bot_token="super-secret-token")
    assert settings.redacted()["telegram_bot_token"] == "***"


def test_effective_limit_cannot_exceed_the_slot_count() -> None:
    settings = Settings(_env_file=None, daily_reel_limit=5, production_slots="09:00,14:00")
    assert settings.slot_limit == 2


def test_production_date_follows_berlin_not_utc() -> None:
    before_midnight = datetime(2026, 11, 18, 22, 30, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 11, 18, 23, 30, tzinfo=timezone.utc)
    assert production_date(before_midnight, "Europe/Berlin") == "2026-11-18"
    assert production_date(after_midnight, "Europe/Berlin") == "2026-11-19"
    with pytest.raises(ValueError):
        production_date(datetime(2026, 11, 18, 12, 0), "Europe/Berlin")


def test_fixed_clock_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 11, 18, 12, 0))
