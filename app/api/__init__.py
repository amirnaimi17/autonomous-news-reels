"""HTTP boundary.

Phase 1 exposes a data function the CLI can share with a later server.
No web framework is mounted yet.
"""

from app.database.models import StatusSnapshot


def health_payload(*, schema_version: str | None, snapshot: StatusSnapshot) -> dict[str, object]:
    """Return a small readiness document. It contains no secrets."""

    return {
        "status": "ok" if schema_version else "not_initialized",
        "schema_version": schema_version,
        "articles": snapshot.article_count,
        "events": snapshot.event_count,
        "completed_today": snapshot.completed_today,
    }
