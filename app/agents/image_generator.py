"""Image generation agent contract."""

from typing import Protocol

from app.schemas.workflow import ImageBatchRequest, ImageBatchResult


class ImageGenerationAgent(Protocol):
    """Create one vertical image per slide through an image provider."""

    name: str

    def run(self, request: ImageBatchRequest) -> ImageBatchResult:
        """Return the written images. Do not invent a scene of the event."""
