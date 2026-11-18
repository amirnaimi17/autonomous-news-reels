"""Load the operator's source list.

The application does not ship feed URLs. An empty configuration stays empty.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.config import NewsSourceConfig, Settings
from app.core.exceptions import ConfigurationError


def configured_news_sources(settings: Settings) -> tuple[NewsSourceConfig, ...]:
    """Return sources from the file when set, otherwise from NEWS_SOURCES."""

    if settings.news_sources_file is not None:
        return _read_file(settings.news_sources_file)
    return settings.news_sources


def _read_file(path: Path) -> tuple[NewsSourceConfig, ...]:
    if not path.is_file():
        raise ConfigurationError(f"News source file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"News source file is not valid JSON: {path}") from exc
    if not isinstance(payload, list):
        raise ConfigurationError("News source file must contain a JSON list")
    try:
        return tuple(NewsSourceConfig.model_validate(item) for item in payload)
    except ValueError as exc:
        raise ConfigurationError(f"News source file is invalid: {exc}") from exc
