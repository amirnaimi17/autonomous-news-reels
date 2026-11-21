"""Shared fixtures.

Tests clear the process environment so a developer .env cannot change them.
"""

import pytest

from app.core.config import ENV_VARS, reset_settings_cache
from app.database.repository import NewsReelsRepository
from tests.support import NOW

# Reel CLI vars are read via os.getenv after optional .env load; clear them in tests.
REEL_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "OPENAI_SCRIPT_MODEL",
    "ELEVENLABS_API_KEY",
    "REEL_WORKING_DIRECTORY",
    "REEL_DATABASE_PATH",
    "REEL_OUTBOX_DIR",
    "REEL_LOCK_PATH",
    "REEL_LOG_PATH",
    "REEL_TIMEZONE",
    "REEL_TARGET_PAGE",
    "REEL_GENERATION_HOURS",
    "REEL_SLOT_GRACE_MINUTES",
    "REEL_NEWS_WINDOW_HOURS",
    "REEL_FRESHNESS_HOURS",
    "REEL_PAID_GENERATION",
    "REEL_PER_REEL_MAX_USD",
    "REEL_DAILY_COST_LIMIT_USD",
    "REEL_MONTHLY_COST_LIMIT_USD",
    "REEL_INGEST_URL",
    "REEL_INGEST_TOKEN",
    "REEL_PYTHON",
    "REEL_SOURCES_FILE",
    "REEL_VOICE_ID",
    "REEL_MAX_ATTEMPTS",
    "REEL_SCRIPT_PROVIDER",
    "REEL_SCRIPT_OUTPUT_DIR",
    "REEL_ELEVENLABS_APPROVED",
    "REEL_AUDIO_OUTPUT_DIR",
    "REEL_EDITORIAL_RANK_PROVIDER",
    "REEL_EDITORIAL_RANK_APPROVED",
    "REEL_EDITORIAL_AUDIENCE_ID",
    "REEL_EDITORIAL_MIN_SCORE",
    "REEL_EDITORIAL_AUDIENCES_FILE",
)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*ENV_VARS, *REEL_ENV_VARS):
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
