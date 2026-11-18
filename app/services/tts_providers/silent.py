"""Offline narration audio.

The file is valid WAV silence whose length follows the word count. It lets the
video step be tested before a speech provider is configured. It is not a voice.
"""

from pathlib import Path
import wave

from app.schemas.content import GeneratedSpeech
from app.schemas.workflow import VoiceRequest


class SilentSpeechProvider:
    """Write silent narration with a duration estimated from the text."""

    name = "silent"

    def __init__(self, *, sample_rate: int = 22050, words_per_second: float = 2.6) -> None:
        if sample_rate < 8000:
            raise ValueError("sample_rate must be at least 8000")
        if words_per_second <= 0:
            raise ValueError("words_per_second must be positive")
        self._sample_rate = sample_rate
        self._words_per_second = words_per_second

    def synthesize(self, request: VoiceRequest) -> GeneratedSpeech:
        words = [word for word in request.narration.split() if word]
        if not words:
            raise ValueError("narration is empty")
        duration = max(1.5, len(words) / self._words_per_second)
        path = Path(request.output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        frame_count = int(round(duration * self._sample_rate))
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self._sample_rate)
            handle.writeframes(b"\x00\x00" * frame_count)
        actual = frame_count / self._sample_rate
        return GeneratedSpeech(
            path=str(path),
            duration_seconds=actual,
            provider=self.name,
            sample_rate=self._sample_rate,
        )
