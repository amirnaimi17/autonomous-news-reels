"""Reel runtime settings.

These are read from the environment only. They do not load the news-selection
Settings object, and they never read an Instagram token.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


def _flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _optional_float(raw: str | None) -> float | None:
    """Parse an optional float env value. Missing/blank means “use audience profile”."""

    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    return float(text)


def _load_dotenv() -> None:
    """Load project ``.env`` into ``os.environ`` without overriding exported vars."""

    try:
        from dotenv import load_dotenv
    except Exception:
        return
    # Prefer the working-directory .env when set, else CWD (CLI from repo root).
    root = Path(os.getenv("REEL_WORKING_DIRECTORY", Path.cwd()))
    candidate = root / ".env"
    if candidate.is_file():
        load_dotenv(candidate, override=False)
    else:
        load_dotenv(override=False)


def _hours(value: str) -> tuple[int, ...]:
    hours: list[int] = []
    for part in value.split(","):
        text = part.strip()
        if not text:
            continue
        hour = int(text)
        if hour < 0 or hour > 23:
            raise ValueError(f"reel hour out of range: {hour}")
        hours.append(hour)
    if len(hours) != len(set(hours)):
        raise ValueError("reel generation hours must be unique")
    return tuple(hours)


@dataclass(frozen=True)
class ReelConfig:
    """Local generation and delivery settings. Publishing stays on the server."""

    database_path: Path
    outbox_dir: Path
    lock_path: Path
    log_path: Path
    timezone: str
    target_page: str
    generation_hours: tuple[int, ...]
    slot_grace_minutes: int
    news_window_hours: int
    freshness_hours: int
    paid_generation: bool
    per_reel_max_usd: float
    daily_cost_limit_usd: float
    monthly_cost_limit_usd: float
    ingest_url: str
    ingest_token: str
    python_executable: str
    working_directory: Path
    sources_file: Path
    voice_id: str
    max_attempts: int
    script_provider: str
    script_model: str
    script_output_dir: Path
    elevenlabs_approved: bool
    audio_output_dir: Path
    editorial_rank_provider: str
    editorial_rank_approved: bool
    editorial_audience_id: str
    editorial_min_score: float | None
    editorial_audiences_file: Path
    narration_review_provider: str = "off"
    narration_review_enabled: bool = False
    narration_review_min_score: float = 80.0
    narration_review_hook_min_score: float = 80.0
    narration_review_curiosity_min_score: float = 75.0
    narration_review_max_rewrites: int = 1
    narration_glossary_file: Path | None = None

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_reel_config() -> ReelConfig:
    """Build the Reel config. Paid generation and the ingest token default off."""

    _load_dotenv()
    root = Path(os.getenv("REEL_WORKING_DIRECTORY", Path.cwd()))
    hours = _hours(os.getenv("REEL_GENERATION_HOURS", "7,11,15,19"))
    script_provider = os.getenv("REEL_SCRIPT_PROVIDER", "off").strip().lower() or "off"
    return ReelConfig(
        database_path=Path(os.getenv("REEL_DATABASE_PATH", root / "data" / "news_reels.db")),
        outbox_dir=Path(os.getenv("REEL_OUTBOX_DIR", root / "storage" / "outbox")),
        lock_path=Path(os.getenv("REEL_LOCK_PATH", root / "storage" / "reels.lock")),
        log_path=Path(os.getenv("REEL_LOG_PATH", root / "storage" / "logs" / "generate-reel.log")),
        timezone=os.getenv("REEL_TIMEZONE", "Europe/Berlin"),
        target_page=os.getenv("REEL_TARGET_PAGE", "almanyar"),
        generation_hours=hours,
        slot_grace_minutes=int(os.getenv("REEL_SLOT_GRACE_MINUTES", "20")),
        news_window_hours=int(os.getenv("REEL_NEWS_WINDOW_HOURS", "36")),
        freshness_hours=int(os.getenv("REEL_FRESHNESS_HOURS", "18")),
        paid_generation=_flag("REEL_PAID_GENERATION", False),
        per_reel_max_usd=float(os.getenv("REEL_PER_REEL_MAX_USD", "0.50")),
        daily_cost_limit_usd=float(os.getenv("REEL_DAILY_COST_LIMIT_USD", "2.00")),
        monthly_cost_limit_usd=float(os.getenv("REEL_MONTHLY_COST_LIMIT_USD", "60")),
        ingest_url=os.getenv("REEL_INGEST_URL", "").strip(),
        ingest_token=os.getenv("REEL_INGEST_TOKEN", "").strip(),
        python_executable=os.getenv("REEL_PYTHON", str(root / ".venv" / "bin" / "python")),
        working_directory=root,
        sources_file=Path(os.getenv("REEL_SOURCES_FILE", root / "config" / "news_sources.json")),
        voice_id=os.getenv("REEL_VOICE_ID", "PEdcOLzbXYhL8IKOswXB"),
        max_attempts=int(os.getenv("REEL_MAX_ATTEMPTS", "3")),
        script_provider=script_provider,
        script_model=os.getenv("OPENAI_SCRIPT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        script_output_dir=Path(
            os.getenv("REEL_SCRIPT_OUTPUT_DIR", root / "storage" / "generated" / "reels" / "scripts")
        ),
        elevenlabs_approved=_flag("REEL_ELEVENLABS_APPROVED", False),
        audio_output_dir=Path(
            os.getenv("REEL_AUDIO_OUTPUT_DIR", root / "storage" / "generated" / "reels" / "audio")
        ),
        editorial_rank_provider=(
            os.getenv("REEL_EDITORIAL_RANK_PROVIDER", "off").strip().lower() or "off"
        ),
        editorial_rank_approved=_flag("REEL_EDITORIAL_RANK_APPROVED", False),
        editorial_audience_id=(
            os.getenv("REEL_EDITORIAL_AUDIENCE_ID", "iranians_in_germany").strip()
            or "iranians_in_germany"
        ),
        editorial_min_score=_optional_float(os.getenv("REEL_EDITORIAL_MIN_SCORE")),
        editorial_audiences_file=Path(
            os.getenv(
                "REEL_EDITORIAL_AUDIENCES_FILE",
                root / "config" / "editorial_audiences.json",
            )
        ),
        narration_review_provider=(
            os.getenv("REEL_NARRATION_REVIEW_PROVIDER", "off").strip().lower() or "off"
        ),
        narration_review_enabled=_flag("REEL_NARRATION_REVIEW_ENABLED", False),
        narration_review_min_score=float(os.getenv("REEL_NARRATION_REVIEW_MIN_SCORE", "80")),
        narration_review_hook_min_score=float(os.getenv("REEL_NARRATION_HOOK_MIN_SCORE", "80")),
        narration_review_curiosity_min_score=float(
            os.getenv("REEL_NARRATION_CURIOSITY_MIN_SCORE", "75")
        ),
        narration_review_max_rewrites=int(os.getenv("REEL_NARRATION_MAX_REWRITES", "1")),
        narration_glossary_file=Path(
            os.getenv(
                "REEL_NARRATION_GLOSSARY_FILE",
                root / "config" / "german_term_glossary.json",
            )
        ),
    )
