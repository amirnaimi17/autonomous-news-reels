#!/usr/bin/env python3
"""Small dependency-free STRUCTURAL validator for Cursor pilot story JSON.

This is not fact-checking or runtime code. It does not use the news database.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from urllib.parse import urlsplit


def validate(data: object, *, allow_demo: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["root must be a JSON object"]

    if data.get("demo") and not allow_demo:
        errors.append("demo artifact is not a real news script (use --allow-demo for fixture checks)")
    if data.get("schema_version") != "pilot-1":
        errors.append("schema_version must be 'pilot-1'")
    for key in ("event_id", "language", "audience", "headline"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            errors.append(f"{key} must be a nonempty string")

    def is_url(x: object) -> bool:
        if not isinstance(x, str):
            return False
        parts = urlsplit(x)
        return parts.scheme in ("http", "https") and bool(parts.netloc)

    sources = data.get("source_urls")
    if not isinstance(sources, list) or not sources or not all(is_url(u) for u in sources):
        errors.append("source_urls must contain one or more valid http(s) URLs")
        sources = []
    if len(sources) != len(set(sources)):
        errors.append("source_urls contains duplicates")

    claims = data.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("claims must be a nonempty list of evidence-linked claims")
    else:
        for i, claim in enumerate(claims, start=1):
            if not isinstance(claim, dict):
                errors.append(f"claim {i} must be an object")
                continue
            if not isinstance(claim.get("text"), str) or not claim["text"].strip():
                errors.append(f"claim {i} needs text")
            urls = claim.get("source_urls")
            if not isinstance(urls, list) or not urls:
                errors.append(f"claim {i} needs source_urls")
            elif any(u not in sources for u in urls):
                errors.append(f"claim {i} cites a URL not in top-level source_urls")

    duration = data.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        errors.append("duration_seconds must be a positive finite number")
        duration = 0
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not 3 <= len(scenes) <= 8:
        errors.append("scenes must contain three to eight scene objects")
    else:
        total = 0.0
        for index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                errors.append(f"scene {index} must be an object")
                continue
            if type(scene.get("number")) is not int or scene["number"] != index:
                errors.append(f"scene {index} must have number {index}")
            seconds = scene.get("duration_seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
                errors.append(f"scene {index} duration_seconds must be positive")
            else:
                total += seconds
            for key in ("narration", "on_screen_text", "visual_prompt"):
                if not isinstance(scene.get(key), str) or not scene[key].strip():
                    errors.append(f"scene {index} needs nonempty {key}")
        if duration and abs(total - duration) > 0.25:
            errors.append(f"scene durations sum to {total:.2f}s but duration_seconds is {duration:.2f}s")
    if not isinstance(data.get("disclaimers"), list) or not all(isinstance(x, str) for x in data["disclaimers"]):
        errors.append("disclaimers must be an array of strings")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate structure of a Cursor Reel pilot JSON file")
    parser.add_argument("story_package", type=Path)
    parser.add_argument("--allow-demo", action="store_true", help="Allow example fixtures explicitly marked demo")
    args = parser.parse_args()
    try:
        doc = json.loads(args.story_package.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as ex:
        print(f"FAIL: cannot load {args.story_package}: {ex}", file=sys.stderr)
        return 2
    issues = validate(doc, allow_demo=args.allow_demo)
    if issues:
        print("FAIL: story JSON structure:")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("PASS: structural checks only — source facts, visuals and audio were NOT verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
