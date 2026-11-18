"""Shared fixtures.

Tests clear the process environment so a developer .env cannot change them.
"""

import pytest

from app.core.config import ENV_VARS, reset_settings_cache
from app.database.repository import NewsReelsRepository
from tests.support import NOW


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def repository(tmp_path) -> NewsReelsRepository:
    database = NewsReelsRepository(tmp_path / "reels.db")
    database.initialize(
        client_id="default",
        name="Default",
        timezone_name="Europe/Berlin",
        daily_reel_limit=3,
        now=NOW,
    )
    return database
