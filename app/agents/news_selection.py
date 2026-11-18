"""News selection agent contract. Ranking and clustering are Phase 2."""

from typing import Protocol

from app.schemas.workflow import SelectionRequest, SelectionResult


class NewsSelectionAgent(Protocol):
    """Choose at most one story, or explain the shortage."""

    name: str

    def run(self, request: SelectionRequest) -> SelectionResult:
        """Rank the supplied candidates against the supplied history."""
