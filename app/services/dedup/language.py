"""Language resources used by clustering.

Stopwords and entity aliases are loaded from files the operator controls.
Missing data leaves that signal empty. It does not invent a match.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?%?")
_PROPER = re.compile(r"\b[A-ZÄÖÜ][A-Za-zÄÖÜäöüß]{1,}\b")
_ACRONYM = re.compile(r"\b[A-Z]{2,}\b")


def load_stopwords(directory: Path) -> dict[str, frozenset[str]]:
    """Load `en.json` style lists. A missing directory yields no lists."""

    if not directory.is_dir():
        return {}
    loaded: dict[str, frozenset[str]] = {}
    for path in sorted(directory.glob("*.json")):
        values = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(values, list):
            raise ValueError(f"{path} must contain a JSON list of words")
        loaded[path.stem.lower()] = frozenset(str(word).lower() for word in values)
    return loaded


def load_aliases(path: Path | None) -> dict[str, str]:
    """Map a surface form to a canonical entity id. Missing file means no aliases."""

    if path is None or not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("entity alias file must be a JSON object")
    aliases: dict[str, str] = {}
    for canonical, surfaces in raw.items():
        if not isinstance(surfaces, list):
            raise ValueError(f"aliases for {canonical} must be a list")
        for surface in surfaces:
            key = _fold(str(surface))
            if key:
                aliases[key] = str(canonical).lower()
    return aliases


def normalized_numbers(text: str) -> set[str]:
    """Return numerals with decimal commas folded to a dot."""

    found: set[str] = set()
    for raw in _NUMBER.findall(text):
        token = raw[:-1] if raw.endswith("%") else raw
        if "," in token and "." not in token:
            token = token.replace(",", ".")
        elif "," in token and "." in token:
            if token.rfind(",") > token.rfind("."):
                token = token.replace(".", "").replace(",", ".")
            else:
                token = token.replace(",", "")
        found.add(token)
    return found


def proper_tokens(text: str) -> set[str]:
    """Names and acronyms as they appear with capitals in the source text."""

    return {token.lower() for token in _PROPER.findall(text)} | {token.lower() for token in _ACRONYM.findall(text)}


def canonical_entities(text: str, aliases: dict[str, str]) -> set[str]:
    """Entity ids whose alias appears in the text."""

    if not aliases:
        return set()
    folded = _fold(text)
    tokens = proper_tokens(text)
    found: set[str] = set()
    for surface, canonical in aliases.items():
        if surface in tokens or (" " in surface and surface in folded):
            found.add(canonical)
    return found


def is_opinion(url: str, title: str) -> bool:
    """Detect opinion packaging from the URL path or a title prefix."""

    lowered_path = url.lower()
    if any(part in lowered_path for part in ("/opinion", "/comment", "/editorial", "/kommentar")):
        return True
    prefix = title.lower().strip()
    return prefix.startswith(("opinion:", "editorial:", "kommentar:", "meinung:"))


def _fold(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).lower().split())
