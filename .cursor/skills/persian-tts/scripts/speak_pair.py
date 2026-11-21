#!/usr/bin/env python3
"""Speak one prepared passage with Farid and Dilara. Same text, rate +0%."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preprocess import load_dictionary, prepare_narration, uncovered_tokens  # noqa: E402
from speak import load_edge_tts, synthesize  # noqa: E402

VOICES = (("fa-IR-FaridNeural", "farid.mp3"), ("fa-IR-DilaraNeural", "dilara.mp3"))


def audio_probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            str(path),
            "-af",
            "volumedetect,silencedetect=n=-35dB:d=0.3",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    levels = {"silence_seconds": []}
    for line in result.stderr.splitlines():
        if "max_volume:" in line:
            levels["max_volume_db"] = float(line.rsplit(":", 1)[1].replace("dB", "").strip())
        elif "mean_volume:" in line:
            levels["mean_volume_db"] = float(line.rsplit(":", 1)[1].replace("dB", "").strip())
        elif "silence_duration:" in line:
            levels["silence_seconds"].append(float(line.rsplit(":", 1)[1].strip()))
    return levels


async def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesize one passage with Farid and Dilara")
    parser.add_argument("--display", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--dictionary", type=Path, default=Path(__file__).resolve().parents[1] / "config" / "pronunciation.json")
    args = parser.parse_args()
    display = args.display.read_text(encoding="utf-8").strip()
    dictionary = load_dictionary(args.dictionary)
    spoken = prepare_narration(display, dictionary)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "narration-display.txt").write_text(display + "\n", encoding="utf-8")
    (args.out_dir / "narration-spoken.txt").write_text(spoken + "\n", encoding="utf-8")
    edge_tts = load_edge_tts()
    rows = []
    for voice, filename in VOICES:
        destination = args.out_dir / filename
        audio = await synthesize(edge_tts, spoken, voice, "+0%", destination)
        levels = audio_probe(destination)
        missing = uncovered_tokens(spoken, [word["text"] for word in audio["words"]])
        long_silence = [gap for gap in levels["silence_seconds"] if gap > 1.2]
        rows.append(
            {
                "voice": voice,
                "rate": "+0%",
                "path": str(destination),
                "duration": audio["duration"],
                "words": audio["words"],
                "missing_tokens": missing,
                "max_volume_db": levels.get("max_volume_db"),
                "mean_volume_db": levels.get("mean_volume_db"),
                "silence_seconds": levels["silence_seconds"],
                "long_silence": long_silence,
                "clipping": levels.get("max_volume_db", 0) >= -0.5,
                "human_listening": "not reviewed",
            }
        )
        print(f"{filename} {audio['duration']}s missing={missing}", flush=True)
    (args.out_dir / "technical.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
