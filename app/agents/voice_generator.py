"""Voice generation agent contract."""

from typing import Protocol

from app.schemas.workflow import VoiceRequest, VoiceResult


class VoiceGenerationAgent(Protocol):
    """Synthesize the approved narration through a TTS provider."""

    name: str

    def run(self, request: VoiceRequest) -> VoiceResult:
        """Return audio metadata, including duration."""
