#!/usr/bin/env python3
"""Structural checks for a Reel visual plan. This does not generate images."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

_IMAGE_FORMATS = {"editorial-photograph", "generated-image"}
_PROMPT_MARKS = ("subject", "composition", "camera", "lighting", "mood", "foreground", "background", "negative space")
_PERSIAN = tuple(chr(code) for code in range(0x0600, 0x0700))


def _persian(text: str) -> bool:
    return any(char in text for char in _PERSIAN)


def validate(data: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["root must be a JSON object"]
    if data.get("width") != 1080 or data.get("height") != 1920:
        errors.append("frame must be 1080x1920")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        return errors + ["scenes must be a nonempty list"]
    prompts: list[str] = []
    image_scenes = 0
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            errors.append(f"scene {index} must be an object")
            continue
        if scene.get("number") != index:
            errors.append(f"scene {index} must have number {index}")
        if not str(scene.get("fact") or "").strip():
            errors.append(f"scene {index} needs a fact")
        if not str(scene.get("format") or "").strip():
            errors.append(f"scene {index} needs a format")
        duration = scene.get("duration_seconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
            errors.append(f"scene {index} duration_seconds must be positive")
        kind = str(scene.get("format") or "")
        if kind == "decorative":
            errors.append(f"scene {index} is decorative")
        prompt = str(scene.get("image_prompt") or "")
        if kind in _IMAGE_FORMATS:
            image_scenes += 1
            if not prompt.strip():
                errors.append(f"scene {index} needs an English image prompt")
            else:
                lowered = prompt.casefold()
                missing = [mark for mark in _PROMPT_MARKS if mark not in lowered]
                if missing:
                    errors.append(f"scene {index} prompt lacks {', '.join(missing)}")
                if not all(color in lowered for color in ("navy", "yellow", "white")):
                    errors.append(f"scene {index} prompt must keep navy, yellow, and white")
                if _persian(prompt):
                    errors.append(f"scene {index} prompt must leave Persian text to Remotion")
                prompts.append(" ".join(lowered.split()))
        elif prompt.strip() and _persian(prompt):
            errors.append(f"scene {index} prompt must leave Persian text to Remotion")
    if len(prompts) != len(set(prompts)):
        errors.append("image prompts repeat a composition")
    forced = data.get("image_count")
    if forced is not None and forced != image_scenes:
        errors.append("image_count does not match the scenes that need a generated image")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a Reel visual plan")
    parser.add_argument("visual_plan", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.visual_plan.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot load {args.visual_plan}: {exc}", file=sys.stderr)
        return 2
    issues = validate(document)
    if issues:
        print("FAIL: visual plan:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("PASS: visual structure only — no image was generated or judged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
