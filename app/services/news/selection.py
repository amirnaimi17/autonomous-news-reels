"""Rank open events for the daily selection list.

The single-story result stays available for a later slot runner. This phase
uses the ordered list and does not reserve a production slot.
"""

from dataclasses import dataclass

from app.schemas.workflow import SelectionResult
from app.services.news.scoring import EventScore


@dataclass(frozen=True)
class RankedEvent:
    """An event that may fill a remaining selection rank."""

    event_id: str
    score: float
    story_class: str
    band: str
    source_count: int
    audience_tier: str = ""


def order_events(events: list[RankedEvent]) -> list[RankedEvent]:
    """Sort by audience tier, then by day, then by score."""

    tier_order = {"A": 0, "B": 1, "C": 2, "": 3}
    band_order = {"today": 0, "yesterday": 1, "older": 2, "outside": 3}
    return sorted(
        events,
        key=lambda event: (
            tier_order.get(event.audience_tier, 9),
            band_order.get(event.band, 9),
            -event.score,
            -event.source_count,
            event.event_id,
        ),
    )


def selection_result_for_first(ranked: list[RankedEvent]) -> SelectionResult:
    """Adapt the top eligible event to the one-story agent result."""

    if not ranked:
        return SelectionResult(
            explanation="No qualifying story is available.",
            shortage_reason="insufficient_qualifying_news",
        )
    best = ranked[0]
    return SelectionResult(
        selected_event_id=best.event_id,
        importance_score=best.score,
        story_class=best.story_class,  # type: ignore[arg-type]
        explanation=f"Selected {best.event_id} from the {best.band} band with score {best.score:.2f}.",
    )


def ranked_from_score(event_id: str, scored: EventScore) -> RankedEvent:
    return RankedEvent(
        event_id=event_id,
        score=scored.score,
        story_class=scored.story_class,
        band=scored.band,
        source_count=scored.source_count,
        audience_tier=scored.audience_tier,
    )
