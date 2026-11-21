"""Evidence check for an editor's audience decision.

The keyword filter does not approve a borderline story. This check only
accepts an approval that names the affected people, the practical effect,
the reason to publish, and a source URL already attached to the story.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

_FIELDS = ("affected_audience", "practical_relevance", "publication_reason")


def editorial_relevance_errors(
    assessment: Mapping[str, object] | None,
    source_urls: Sequence[str],
) -> list[str]:
    """Return why an assessment cannot support publication."""

    if not isinstance(assessment, Mapping):
        return ["an audience assessment is required"]
    errors: list[str] = []
    decision = assessment.get("decision")
    if decision not in {"approve", "reject"}:
        errors.append("decision must be approve or reject")
    for field in _FIELDS:
        value = assessment.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is required")
    evidence = assessment.get("evidence_urls")
    if not isinstance(evidence, list) or not evidence:
        errors.append("evidence_urls must list at least one source")
    else:
        known = set(source_urls)
        for url in evidence:
            if not isinstance(url, str) or url not in known:
                errors.append("evidence_urls must come from the story sources")
                break
    return errors


def editorial_approves(assessment: Mapping[str, object] | None, source_urls: Sequence[str]) -> bool:
    """True only when the editor approved and the evidence check passed."""

    if not isinstance(assessment, Mapping) or assessment.get("decision") != "approve":
        return False
    return not editorial_relevance_errors(assessment, source_urls)
