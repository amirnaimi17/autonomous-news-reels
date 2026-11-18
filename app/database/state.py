"""Generation state machine.

COMPLETED and SKIPPED are terminal. FAILED resumes from the last state whose
artifact was stored, and it may move only one step forward from there.
"""

from app.schemas.content import GenerationState

_NEXT: dict[GenerationState, GenerationState] = {
    GenerationState.DISCOVERED: GenerationState.SELECTED,
    GenerationState.SELECTED: GenerationState.SCRIPT_GENERATED,
    GenerationState.SCRIPT_GENERATED: GenerationState.IMAGES_GENERATED,
    GenerationState.IMAGES_GENERATED: GenerationState.AUDIO_GENERATED,
    GenerationState.AUDIO_GENERATED: GenerationState.VIDEO_RENDERED,
    GenerationState.VIDEO_RENDERED: GenerationState.COMPLETED,
}


def allowed_targets(
    current: GenerationState,
    last_successful: GenerationState | None,
) -> frozenset[GenerationState]:
    """Return the states a job is allowed to enter next."""

    if current in {GenerationState.COMPLETED, GenerationState.SKIPPED}:
        return frozenset()
    if current is GenerationState.FAILED:
        anchor = _resume_anchor(last_successful)
        allowed = {anchor, GenerationState.SKIPPED}
        nxt = _NEXT.get(anchor)
        if nxt is not None:
            allowed.add(nxt)
        return frozenset(allowed)
    allowed = {GenerationState.FAILED, GenerationState.SKIPPED}
    nxt = _NEXT.get(current)
    if nxt is not None:
        allowed.add(nxt)
    return frozenset(allowed)


def _resume_anchor(last_successful: GenerationState | None) -> GenerationState:
    if last_successful is None or last_successful in {
        GenerationState.FAILED,
        GenerationState.SKIPPED,
        GenerationState.COMPLETED,
    }:
        return GenerationState.SELECTED
    return last_successful
