#!/usr/bin/env python3
"""Speak the regression sentences with Farid and Dilara. No espeak."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preprocess import load_dictionary, to_spoken  # noqa: E402
from speak import load_edge_tts, synthesize  # noqa: E402
from test_cases import CASES  # noqa: E402

VOICES = ("fa-IR-FaridNeural", "fa-IR-DilaraNeural")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Farid and Dilara on the regression sentences")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    edge_tts = load_edge_tts()
    dictionary = load_dictionary(Path(__file__).resolve().parents[1] / "config" / "pronunciation.json")
    rows = []
    for index, (raw, _expected) in enumerate(CASES, start=1):
        spoken = to_spoken(raw, dictionary)
        for voice in VOICES:
            slug = "farid" if "Farid" in voice else "dilara"
            destination = args.out_dir / f"{index:02d}-{slug}.mp3"
            spoken_audio = await synthesize(edge_tts, spoken, voice, "+0%", destination)
            rows.append(
                {
                    "index": index,
                    "voice": voice,
                    "rate": "+0%",
                    "display": raw,
                    "spoken": spoken,
                    "duration": spoken_audio["duration"],
                    "path": str(destination),
                    "human_listening": "not reviewed",
                }
            )
            print(f"{destination.name} {spoken_audio['duration']}s", flush=True)
    (args.out_dir / "comparison.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
