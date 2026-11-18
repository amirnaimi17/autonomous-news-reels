"""Duplicate-comparison port.

The default judge declines to decide. The selection policy treats that as a
duplicate when fail-closed deduplication is on, which is the default.
"""

from typing import Literal, Protocol

Judgement = Literal["same_event", "update", "distinct", "uncertain"]


class SemanticDuplicateJudge(Protocol):
    """Optional model check for a pair the deterministic matcher finds unclear."""

    name: str

    def compare(self, left: str, right: str) -> Judgement:
        """Compare two story summaries."""


class UncertainJudge:
    """Working offline judge. It never invents a match or a distinction."""

    name = "uncertain"

    def compare(self, left: str, right: str) -> Judgement:
        if not left.strip() or not right.strip():
            return "uncertain"
        return "uncertain"
