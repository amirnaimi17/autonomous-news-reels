"""Translation port.

`none` is the only provider wired into configuration. A future provider
implements this same method and reads its credential from the environment.
"""

from typing import Protocol


class Translator(Protocol):
    """Rewrite text into a pivot language. Returning None means no translation."""

    name: str

    def translate(self, text: str, source_language: str, pivot_language: str) -> str | None:
        """Return pivot-language text, or None when this provider cannot translate."""


class NoneTranslator:
    """Configured default. Cross-language paraphrase matching stays unavailable."""

    name = "none"

    def translate(self, text: str, source_language: str, pivot_language: str) -> str | None:
        return None


class DictionaryTranslator:
    """Test double. Keys are `(language, folded source text)`."""

    name = "dictionary"

    def __init__(self, table: dict[tuple[str, str], str]) -> None:
        self._table = table

    def translate(self, text: str, source_language: str, pivot_language: str) -> str | None:
        folded = " ".join(text.split()).lower()
        return self._table.get((source_language.lower(), folded))
