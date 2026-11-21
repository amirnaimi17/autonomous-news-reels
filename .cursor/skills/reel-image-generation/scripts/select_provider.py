#!/usr/bin/env python3
"""Print the image-provider decision for this machine."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from providers import comfyui_reachable, load_hardware, select_provider  # noqa: E402


def main() -> None:
    hardware = load_hardware()
    print(json.dumps(select_provider(hardware, comfy_up=comfyui_reachable()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
