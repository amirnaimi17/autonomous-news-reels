"""Choose an image provider from measured hardware. No model downloads."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

# Approximate weight footprints in MiB. These are gates, not benchmark results.
MODEL_VRAM_MIB = {
    "sdxl": 8192,
    "flux-schnell": 12288,
    "flux-dev": 24576,
}

ROOT = Path(__file__).resolve().parents[1]


def load_hardware(path: Path | None = None) -> dict:
    return json.loads((path or ROOT / "config" / "hardware.json").read_text(encoding="utf-8"))


def fitting_local_models(vram_mib: int) -> list[str]:
    return [name for name, need in MODEL_VRAM_MIB.items() if need <= vram_mib]


def comfyui_reachable(url: str = "http://127.0.0.1:8188/system_stats", timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def select_provider(hardware: dict, *, comfy_up: bool) -> dict:
    vram = int(hardware["vram_mib"])
    local = fitting_local_models(vram)
    decision = {
        "selected": "cursor-generate-image",
        "reason": "Cursor GenerateImage already produced the pilot illustrations. Local diffusion models in this catalog need more than the measured VRAM.",
        "local_models_that_fit": local,
        "rejected": {name: f"needs {need} MiB" for name, need in MODEL_VRAM_MIB.items() if need > vram},
        "comfyui": "reachable" if comfy_up else "not running",
        "replace_cursor": False,
    }
    if comfy_up and local:
        decision["comfyui"] = "reachable but unused until a fitting model is installed and compared"
    return decision
