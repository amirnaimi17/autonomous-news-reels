"""Video production agent contract. FFmpeg rendering is Phase 5."""

from typing import Protocol

from app.schemas.workflow import VideoRenderRequest, VideoRenderResult


class VideoProductionAgent(Protocol):
    """Render a vertical H.264 reel from slides and narration."""

    name: str

    def run(self, request: VideoRenderRequest) -> VideoRenderResult:
        """Return the rendered file. The orchestrator validates it afterwards."""
