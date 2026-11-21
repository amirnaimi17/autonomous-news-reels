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

    @property
    def zone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_reel_config() -> ReelConfig:
    """Build the Reel config. Paid generation and the ingest token default off."""

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
    )
