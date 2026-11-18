"""News research agent contract. The RSS client is Phase 2."""

from typing import Protocol

from app.schemas.workflow import ResearchRequest, ResearchResult


class NewsResearchAgent(Protocol):
    """Collect and normalize articles inside the requested window."""

    name: str

    def run(self, request: ResearchRequest) -> ResearchResult:
        """Return discovered articles and per-source failures."""
