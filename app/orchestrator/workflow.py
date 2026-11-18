"""Fixed production order. Execution of the steps is added with the agents."""

from collections.abc import Sequence
from enum import Enum


class WorkflowStep(str, Enum):
    """One orchestrator step, in the only legal order."""

    RESEARCH = "research"
    SELECT = "select"
    RESERVE_SLOT = "reserve_slot"
    RESERVE_STORY = "reserve_story"
    WRITE_SCRIPT = "write_script"
    GENERATE_IMAGES = "generate_images"
    GENERATE_VOICE = "generate_voice"
    RENDER_VIDEO = "render_video"
    VALIDATE_VIDEO = "validate_video"
    COMPLETE = "complete"
    NOTIFY = "notify"


WORKFLOW_STEPS: tuple[WorkflowStep, ...] = (
    WorkflowStep.RESEARCH,
    WorkflowStep.SELECT,
    WorkflowStep.RESERVE_SLOT,
    WorkflowStep.RESERVE_STORY,
    WorkflowStep.WRITE_SCRIPT,
    WorkflowStep.GENERATE_IMAGES,
    WorkflowStep.GENERATE_VOICE,
    WorkflowStep.RENDER_VIDEO,
    WorkflowStep.VALIDATE_VIDEO,
    WorkflowStep.COMPLETE,
    WorkflowStep.NOTIFY,
)


class WorkflowOrchestrator:
    """Owns the step order.

    Phase 1 does not execute the pipeline. The research, selection, and render
    agents are not implemented yet, and a stub run would claim that they are.
    """

    def __init__(self, steps: Sequence[WorkflowStep] | None = None) -> None:
        self.steps = tuple(WORKFLOW_STEPS if steps is None else steps)
