"""Voice selection. Aran is the production default. Edge Farid is the fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAID_ENV = {
    "elevenlabs": "ELEVENLABS_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def load_catalog(path: Path | None = None) -> dict:
    return json.loads((path or ROOT / "config" / "voices.json").read_text(encoding="utf-8"))


def select_voice(*, catalog: dict | None = None) -> dict:
    """Use Aran when the ElevenLabs key is set. Otherwise keep Farid and send nothing paid."""

    voices = catalog or load_catalog()
    production = voices["production"]
    fallback = voices["fallback"]
    if os.environ.get(PAID_ENV["elevenlabs"]):
        return {
            "selected": production["provider"],
            "name": production["name"],
            "model": production["model"],
            "voice_id": production["voice_id"],
            "language_code": production["language_code"],
            "speed": production["speed"],
            "fallback": fallback,
            "options": voices["options"],
            "reason": production["reason"],
        }
    return {
        "selected": fallback["provider"],
        "name": fallback["name"],
        "model": fallback["model"],
        "rate": fallback["rate"],
        "fallback_reason": f"{PAID_ENV['elevenlabs']} is unset, so Edge TTS is used and no paid request is sent.",
        "production": production,
        "options": voices["options"],
    }
