"""Deterministic text fingerprints.

These functions do not decide that two stories are the same event. The
selection agent applies the configured thresholds in Phase 2. Keeping the
functions pure makes that decision testable without a model.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable

_OUTLET_SUFFIXES = frozenset(
    {
        "bbc",
        "bbc news",
        "reuters",
        "associated press",
        "ap news",
        "the guardian",
        "the new york times",
        "al jazeera",
        "npr",
    }
)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "been",
        "before",
        "after",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "over",
        "that",
        "the",
        "this",
        "to",
        "was",
        "were",
        "with",
    }
)

_TOKEN = re.compile(r"[a-z0-9äöüàáâãåæçèéêëìíîïñòóôõøùúûýÿß]+(?:'[a-z0-9äöüàáâãåæçèéêëìíîïñòóôõøùúûýÿß]+)?")


def normalize_headline(title: str) -> str:
    """Lowercase a headline and remove a trailing outlet name."""

    text = unicodedata.normalize("NFKC", title).lower().replace("’", "'")
    text = text.replace("—", " - ").replace("–", " - ").replace("|", " - ")
    text = " ".join(text.split())
    while " - " in text:
        head, tail = text.rsplit(" - ", 1)
        if tail.strip(" .") not in _OUTLET_SUFFIXES or not head.strip():
            break
        text = head.strip()
    text = re.sub(r"[^\w\s'-]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def significant_tokens(text: str, stopwords: Iterable[str] | None = None) -> tuple[str, ...]:
    """Return meaningful tokens in reading order.

    The default stopword list is English. Pass the list for the article's
    language so German text is not filtered with English words.
    """

    blocked = _STOPWORDS if stopwords is None else frozenset(word.lower() for word in stopwords)
    return tuple(
        token
        for token in _TOKEN.findall(normalize_headline(text))
        if token not in blocked and len(token) > 1
    )


def title_fingerprint(title: str, stopwords: Iterable[str] | None = None) -> str:
    """Hash the sorted significant tokens so word order does not matter."""

    tokens = tuple(sorted(set(significant_tokens(title, stopwords))))
    if not tokens:
        raise ValueError("headline has no significant tokens")
    return hashlib.sha256("|".join(tokens).encode("utf-8")).hexdigest()


def block_key(title: str, stopwords: Iterable[str] | None = None) -> str:
    """Coarse bucket used to group events that may describe the same story."""

    tokens = significant_tokens(title, stopwords)
    return tokens[0] if tokens else "general"


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    """Similarity of two token sets, from 0 to 1."""

    first = set(left)
    second = set(right)
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def simhash64(text: str, stopwords: Iterable[str] | None = None) -> str:
    """64-bit SimHash of significant tokens, as 16 hex characters."""

    tokens = significant_tokens(text, stopwords)
    if not tokens:
        raise ValueError("text has no tokens to hash")
    weights = [0] * 64
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        value = int.from_bytes(digest[:8], "big")
        for index in range(64):
            weights[index] += 1 if value & (1 << index) else -1
    result = 0
    for index, weight in enumerate(weights):
        if weight > 0:
            result |= 1 << index
    return f"{result:016x}"


def hamming_distance(left: str, right: str) -> int:
    """Bit distance between two hex SimHash values."""

    if len(left) != 16 or len(right) != 16:
        raise ValueError("simhash values must be 16 hex characters")
    return (int(left, 16) ^ int(right, 16)).bit_count()
