"""News research agent.

The agent returns articles and per-source failures. It does not write the database.
"""

from app.schemas.workflow import ResearchRequest, ResearchResult
from app.services.news_sources.rss import RssNewsSource
from app.services.news_sources.static import StaticNewsSource


class SourceResearchAgent:
    """Fetch the requested window from the injected source."""

    name = "news_research"

    def __init__(self, source: RssNewsSource | StaticNewsSource) -> None:
        self._source = source

    def run(self, request: ResearchRequest) -> ResearchResult:
        return self._source.fetch(window_start=request.window_start, window_end=request.window_end)
