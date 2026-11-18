"""Acceptance rules for a finished reel.

Phase 5 fills a VideoProbe from ffprobe. The rules live here so the renderer
and the tests share one definition of a publishable file.
"""

from dataclasses import dataclass

from app.core.exceptions import VideoValidationError

_H264 = {"h264", "avc1"}


@dataclass(frozen=True)
class VideoProbe:
    """Facts about a media file. This is not a guess."""

    width: int
    height: int
    duration_seconds: float
    video_codec: str
    audio_codec: str | None
    has_audio: bool


def validate_reel_video(
    probe: VideoProbe,
    *,
    expected_width: int,
    expected_height: int,
    min_duration: float,
    max_duration: float,
) -> None:
    """Raise VideoValidationError when the file cannot be accepted as a reel."""

    problems: list[str] = []
    if probe.width != expected_width or probe.height != expected_height:
        problems.append(
            f"resolution is {probe.width}x{probe.height}, expected {expected_width}x{expected_height}"
        )
    if probe.video_codec.lower() not in _H264:
        problems.append(f"video codec {probe.video_codec} is not H.264")
    if not probe.has_audio or not probe.audio_codec:
        problems.append("audio stream is missing")
    if not min_duration <= probe.duration_seconds <= max_duration:
        problems.append(
            f"duration {probe.duration_seconds:.2f}s is outside {min_duration:.0f}-{max_duration:.0f}s"
        )
    if problems:
        raise VideoValidationError("; ".join(problems))
