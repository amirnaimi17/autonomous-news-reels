"""Persian Reel narration through the existing persian-tts ElevenLabs client.

This module does not reimplement HTTP. It loads
``.cursor/skills/persian-tts/scripts/elevenlabs.py`` and forwards to ``synthesize``
with an injectable transport. Live calls require an explicit approval flag.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from typing import Any, Callable

ARAN_VOICE = "PEdcOLzbXYhL8IKOswXB"
MODEL_ID = "eleven_v4"
SPEED = 1.0
# Measured from the approved Aran sample: 216 characters in 18.08 seconds.
CHARS_PER_SECOND = 216 / 18.08
ELEVENLABS_USD_PER_CHAR = 0.08 / 1000

Transport = Callable[[dict[str, Any], str], bytes | tuple[bytes, dict]]

_ROOT = Path(__file__).resolve().parents[2]
_ELEVENLABS = _ROOT / ".cursor" / "skills" / "persian-tts" / "scripts" / "elevenlabs.py"
_PREPROCESS = _ROOT / ".cursor" / "skills" / "persian-tts" / "scripts" / "preprocess.py"
_VOICES = _ROOT / ".cursor" / "skills" / "persian-tts" / "config" / "voices.json"
_PRONUNCIATION = _ROOT / ".cursor" / "skills" / "persian-tts" / "config" / "pronunciation.json"
_DEFAULT_LEDGER = _ROOT / "storage" / "cost-ledger" / "usage.jsonl"


def load_elevenlabs():
    """Import the skill ElevenLabs module once per process use."""

    spec = importlib.util.spec_from_file_location("reel_persian_tts_elevenlabs", _ELEVENLABS)
    if spec is None or spec.loader is None:
        raise RuntimeError("ElevenLabs client is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_preprocess():
    spec = importlib.util.spec_from_file_location("reel_persian_tts_preprocess", _PREPROCESS)
    if spec is None or spec.loader is None:
        raise RuntimeError("Persian TTS preprocess module is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def production_voice_id() -> str:
    if not _VOICES.is_file():
        return ARAN_VOICE
    data = json.loads(_VOICES.read_text(encoding="utf-8"))
    production = data.get("production") or {}
    return str(production.get("voice_id") or ARAN_VOICE)


def prepare_spoken(text: str) -> str:
    """Convert display narration into the spoken form Aran expects."""

    preprocess = load_preprocess()
    dictionary = {}
    if _PRONUNCIATION.is_file():
        dictionary = preprocess.load_dictionary(_PRONUNCIATION)
    return preprocess.prepare_narration(text, dictionary)


def estimate_duration_seconds(spoken: str) -> float:
    return round(max(len(spoken.strip()) / CHARS_PER_SECOND, 0.5), 2)


def estimate_usd(spoken: str) -> float:
    return round(len(spoken.strip()) * ELEVENLABS_USD_PER_CHAR, 6)


def probe_audio_duration(path: Path) -> float | None:
    """Return ffprobe duration for an audio file, or None when ffprobe is unavailable."""

    try:
        completed = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        payload = json.loads(completed.stdout)
        value = float(payload.get("format", {}).get("duration") or 0)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def narrate_persian(
    text: str,
    voice_id: str | None = None,
    *,
    out_path: Path,
    approved: bool = False,
    transport: Transport | None = None,
    ledger_path: Path | None = None,
    prepare: bool = True,
) -> dict[str, Any]:
    """Synthesize Persian narration to MP3 using the skill client.

    Live HTTP requires ``approved=True`` and ``ELEVENLABS_API_KEY``. Tests inject
    ``transport`` and never hit the network.
    """

    display = text.strip()
    if not display:
        raise RuntimeError("narration text is empty")
    spoken = prepare_spoken(display) if prepare else display
    chosen = (voice_id or production_voice_id()).strip() or ARAN_VOICE
    module = load_elevenlabs()
    # Build the request first so refusal messages can name the endpoint.
    request = module.speech_request(spoken, chosen)
    if not approved and transport is None:
        raise RuntimeError(
            "ElevenLabs live narration is disabled. "
            "Pass approved=True / REEL_ELEVENLABS_APPROVED=true only for an explicit paid test, "
            f"or inject a transport. Request would have been {request['url']}"
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio = module.synthesize(
        spoken,
        chosen,
        approved=True if transport is not None else approved,
        voice_rate_confirmed=True,
        ledger_path=Path(ledger_path) if ledger_path is not None else _DEFAULT_LEDGER,
        out_path=out_path,
        transport=transport,
    )
    if not out_path.is_file():
        out_path.write_bytes(audio)
    duration = probe_audio_duration(out_path)
    if duration is None:
        duration = estimate_duration_seconds(spoken)
    return {
        "path": str(out_path),
        "provider": "elevenlabs",
        "voice_id": chosen,
        "model_id": MODEL_ID,
        "speed": SPEED,
        "duration_seconds": float(duration),
        "characters": len(spoken),
        "usd": estimate_usd(spoken),
        "display_text": display,
        "spoken_text": spoken,
        "request_url": request["url"],
    }


def default_audio_path(audio_dir: Path, text: str) -> Path:
    digest = hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]
    return Path(audio_dir) / f"narration-{digest}.mp3"
