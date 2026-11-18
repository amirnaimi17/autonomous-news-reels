"""FFmpeg capability detection.

Rendering is Phase 5. This module only chooses an encoder the machine has.
NVENC is preferred when it is present because this workstation has a Quadro
T2000 and a tested H.264 NVENC path. CPU libx264 remains the fallback.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from app.core.exceptions import ConfigurationError

_ENCODER_LINE = re.compile(r"(?m)^\s*\S+\s+([A-Za-z0-9_]+)\s")


@dataclass(frozen=True)
class FFmpegCapabilities:
    """What the local ffmpeg binary can encode."""

    available: bool
    version: str | None
    h264_nvenc: bool
    libx264: bool
    error: str | None


def encoder_names(encoders_stdout: str) -> set[str]:
    """Parse `ffmpeg -encoders` output."""

    return set(_ENCODER_LINE.findall(encoders_stdout))


def capabilities_from_output(version_stdout: str, encoders_stdout: str) -> FFmpegCapabilities:
    """Build a capability report from ffmpeg text."""

    names = encoder_names(encoders_stdout)
    version = version_stdout.splitlines()[0].strip() if version_stdout.strip() else None
    return FFmpegCapabilities(
        available=True,
        version=version,
        h264_nvenc="h264_nvenc" in names,
        libx264="libx264" in names,
        error=None,
    )


def probe_ffmpeg(ffmpeg_bin: str = "ffmpeg") -> FFmpegCapabilities:
    """Run ffmpeg and report H.264 encoders. A missing binary is reported, not hidden."""

    try:
        version = subprocess.run(
            [ffmpeg_bin, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        encoders = subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return FFmpegCapabilities(False, None, False, False, str(exc))
    if version.returncode != 0:
        error = (version.stderr or version.stdout or "ffmpeg -version failed").strip()
        return FFmpegCapabilities(False, None, False, False, error)
    return capabilities_from_output(version.stdout, encoders.stdout)


def select_encoder(capabilities: FFmpegCapabilities, preference: str) -> str:
    """Resolve auto, NVENC, or libx264. Missing encoders raise."""

    if not capabilities.available:
        detail = capabilities.error or "ffmpeg is not available"
        raise ConfigurationError(detail)
    if preference == "libx264":
        if not capabilities.libx264:
            raise ConfigurationError("libx264 is not available in this ffmpeg build")
        return "libx264"
    if preference == "h264_nvenc":
        if not capabilities.h264_nvenc:
            raise ConfigurationError("h264_nvenc is not available in this ffmpeg build")
        return "h264_nvenc"
    if preference == "auto":
        if capabilities.h264_nvenc:
            return "h264_nvenc"
        if capabilities.libx264:
            return "libx264"
        raise ConfigurationError("no H.264 encoder is available")
    raise ConfigurationError(f"unknown video encoder: {preference}")
