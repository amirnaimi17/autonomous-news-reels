"""Technical QA helpers for rendered Reels.

Reuses the contact-sheet approach from the reel-quality-assurance skill without
requiring the skill's CLI image/manifest arguments.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any

from app.reels.render import probe_media, validate_reel_probe

_CHECK_REEL = (
    Path(__file__).resolve().parents[2]
    / ".cursor"
    / "skills"
    / "reel-quality-assurance"
    / "scripts"
    / "check_reel.py"
)


def load_check_reel():
    spec = importlib.util.spec_from_file_location("reel_qa_check_reel", _CHECK_REEL)
    if spec is None or spec.loader is None:
        raise RuntimeError("reel-quality-assurance check_reel.py is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_contact_sheet(video: Path, destination: Path, *, frames: int = 4) -> Path:
    """Extract evenly spaced frames and stack them into a contact sheet."""

    probe = probe_media(video)
    duration = float(probe.get("duration_seconds") or 0)
    if duration <= 0:
        raise RuntimeError(f"cannot build contact sheet; no duration for {video}")
    if frames < 1:
        raise ValueError("frames must be >= 1")
    # Match the skill's sampling style for four frames.
    if frames == 4:
        stamps = [duration * 0.12, duration * 0.37, duration * 0.62, duration * 0.87]
    else:
        stamps = [duration * ((index + 0.5) / frames) for index in range(frames)]
    module = load_check_reel()
    module.contact_sheet(Path(video), stamps, Path(destination))
    return Path(destination)


def audio_levels(path: Path) -> dict[str, float]:
    """Reuse the skill volumedetect helper for silence checks."""

    module = load_check_reel()
    return module.volume(Path(path))


def technical_qa_report(
    video: Path,
    *,
    contact_sheet: Path | None = None,
    narration: str = "",
    min_seconds: float = 1.0,
    max_seconds: float = 900.0,
    require_audible_audio: bool = False,
) -> dict[str, Any]:
    """Build a compact technical QA report for the pilot."""

    probe = probe_media(video)
    problems = list(validate_reel_probe(probe, min_seconds=min_seconds, max_seconds=max_seconds))
    levels: dict[str, float] = {}
    try:
        levels = audio_levels(video)
    except Exception:
        levels = {}
    mean_db = levels.get("mean_volume_db")
    audible = mean_db is not None and float(mean_db) > -45.0
    if require_audible_audio and not audible:
        problems.append("audio silent or near-silent")
    sheet = None
    if contact_sheet is not None:
        sheet = write_contact_sheet(video, contact_sheet)
    checksum_ok = bool(probe.get("checksum_sha256")) and Path(video).is_file()
    checks = [
        {"name": "resolution", "ok": "resolution" not in problems, "detail": f"{probe.get('width')}x{probe.get('height')}"},
        {"name": "video_codec", "ok": "video codec" not in problems, "detail": str(probe.get("video_codec"))},
        {"name": "audio_codec", "ok": "audio codec" not in problems, "detail": str(probe.get("audio_codec"))},
        {"name": "duration", "ok": "duration" not in problems, "detail": f"{probe.get('duration_seconds')}"},
        {"name": "file_integrity", "ok": checksum_ok, "detail": str(probe.get("checksum_sha256") or "")[:16]},
        {
            "name": "narration_present",
            "ok": bool(str(narration).strip()),
            "detail": f"{len(str(narration).strip())} characters",
        },
        {
            "name": "audio_not_silent",
            "ok": audible if levels else (not require_audible_audio),
            "detail": f"mean_volume_db={mean_db}",
        },
    ]
    return {
        "technical_pass": not problems and checksum_ok and bool(str(narration).strip()) and (audible if require_audible_audio else True),
        "problems": problems,
        "checks": checks,
        "probe": probe,
        "audio_levels": levels,
        "contact_sheet": str(sheet) if sheet and Path(sheet).is_file() else None,
        "human_review": {
            "voice_naturalness": "not reviewed",
            "design_quality": "not reviewed",
            "note": "A technical pass does not mean the voice or the design passed human review.",
        },
    }
