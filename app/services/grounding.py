"""Checks that narration does not introduce figures absent from the source."""

from __future__ import annotations

import re

from app.core.exceptions import GroundingError

# ASCII, Persian (U+06F0–U+06F9), and Arabic-Indic (U+0660–U+0669) digits.
_DIGIT = r"0-9\u06F0-\u06F9\u0660-\u0669"
_DECIMAL = r".\u066B"
_THOUSANDS = r",\u066C\u060C"
_PERCENT_CHARS = "%\u066A٪"

_NUMBER = re.compile(
    rf"(?<![{_DIGIT}])"
    rf"("
    rf"[{_DIGIT}]{{1,3}}(?:[{_THOUSANDS}][{_DIGIT}]{{3}})+(?:[{_DECIMAL}][{_DIGIT}]+)?"
    rf"|[{_DIGIT}]+(?:[{_DECIMAL}][{_DIGIT}]+)?"
    rf")"
    rf"([{_PERCENT_CHARS}])?"
    rf"(?![{_DIGIT}])"
)

_DIGIT_TO_ASCII = str.maketrans(
    {
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)


def to_ascii_digits(text: str) -> str:
    """Map Persian and Arabic-Indic digits to ASCII digits."""

    return (text or "").translate(_DIGIT_TO_ASCII)


def extract_numbers(text: str) -> list[str]:
    """Return numerals as they appear in the text (any supported digit script)."""

    found: list[str] = []
    for match in _NUMBER.finditer(text or ""):
        token = match.group(1)
        if match.group(2):
            token = token + match.group(2)
        found.append(token)
    return found


def normalize_numeral(token: str) -> str:
    """Deterministic numeral key for comparison across digit scripts and separators.

    ``25``, ``۲۵``, and ``٢٥`` all become ``25``. Percent marks and thousands
    separators are stripped. Decimal separators become ``.``.
    """

    text = to_ascii_digits(token or "")
    text = (
        text.replace("\u066A", "")  # Arabic percent sign
        .replace("%", "")
        .replace("٪", "")
        .replace("\u066B", ".")  # Arabic decimal separator
        .replace("\u066C", "")  # Arabic thousands separator
        .replace("\u060C", "")  # Arabic comma
        .replace(",", "")
        .strip()
    )
    return text


# Backward-compatible private alias used by older imports/tests.
_normalize = normalize_numeral


def _ascii_source_blob(source_text: str) -> str:
    """Source text with digits ASCII-normalized and separators stripped for substring checks."""

    text = to_ascii_digits(source_text or "")
    return (
        text.replace("\u066B", ".")
        .replace("\u066C", "")
        .replace("\u060C", "")
        .replace(",", "")
        .replace("%", "")
        .replace("\u066A", "")
        .replace("٪", "")
    )


def numbers_missing_from_source(narration: str, source_text: str) -> list[str]:
    """Return narration numerals that the source text does not contain.

    Comparison is script-agnostic: Persian, Arabic-Indic, and ASCII forms of the
    same figure match. Genuinely unsupported numbers are still reported.
    """

    source_norms = {normalize_numeral(token) for token in extract_numbers(source_text)}
    source_norms.discard("")
    collapsed_source = _ascii_source_blob(source_text)
    missing: list[str] = []
    for token in extract_numbers(narration):
        norm = normalize_numeral(token)
        if not norm:
            continue
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
