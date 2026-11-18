"""Checks that narration does not introduce figures absent from the source."""

import re

from app.core.exceptions import GroundingError

_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?%?)(?![\w.])")


def extract_numbers(text: str) -> list[str]:
    """Return numerals as they appear in the text."""

    return [match.group(1) for match in _NUMBER.finditer(text)]


def _normalize(token: str) -> str:
    return token.replace(",", "").replace("%", "")


def numbers_missing_from_source(narration: str, source_text: str) -> list[str]:
    """Return narration numerals that the source text does not contain."""

    source_norms = {_normalize(token) for token in extract_numbers(source_text)}
    collapsed_source = source_text.replace(",", "")
    missing: list[str] = []
    for token in extract_numbers(narration):
        norm = _normalize(token)
        if norm in source_norms or norm in collapsed_source:
            continue
        missing.append(token)
    return missing


def require_grounded_numbers(narration: str, source_text: str) -> None:
    """Raise when the narration adds a figure the source did not state."""

    missing = numbers_missing_from_source(narration, source_text)
    if missing:
        joined = ", ".join(missing)
        raise GroundingError(f"narration contains figures that are not in the source: {joined}")
