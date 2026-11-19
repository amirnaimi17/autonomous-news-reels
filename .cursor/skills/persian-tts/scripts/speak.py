#!/usr/bin/env python3
"""Persian narration via Microsoft Edge TTS. Never calls espeak-ng."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_VOICE = "fa-IR-FaridNeural"
TICKS_PER_SECOND = 10_000_000


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_edge_tts():
    if "espeak" in Path(sys.executable).name.lower():
        fail("refusing to run under an espeak interpreter")
    try:
        import edge_tts
    except ImportError:
        fail(
            "edge-tts is not installed for this Python. "
            "From the repo root run: python3 -m venv .cursor/skills/persian-tts/.venv && "
            ".cursor/skills/persian-tts/.venv/bin/pip install -r .cursor/skills/persian-tts/requirements.txt. "
            "Do not use espeak-ng."
        )
    return edge_tts


def rate_percent(rate: str) -> int:
    if not rate.endswith("%") or rate[0] not in "+-":
        fail(f"rate must look like +0% or -10%, got {rate}")
    return int(rate[:-1])


def format_rate(percent: int) -> str:
    return f"{percent:+d}%"


def probe_duration(path: Path) -> float:
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        fail(completed.stderr.strip() or f"ffprobe failed for {path}")
    return float(completed.stdout.strip())


async def synthesize(edge_tts, text: str, voice: str, rate: str, destination: Path) -> dict:
    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        volume="+0%",
        pitch="+0Hz",
        boundary="WordBoundary",
    )
    audio = bytearray()
    words = []
    async for chunk in communicate.stream():
        kind = chunk["type"]
        if kind == "audio":
            audio.extend(chunk["data"])
        elif kind == "WordBoundary":
            start = float(chunk["offset"]) / TICKS_PER_SECOND
            end = float(chunk["offset"] + chunk["duration"]) / TICKS_PER_SECOND
            words.append({"text": chunk["text"], "start": round(start, 3), "end": round(end, 3)})
    if not audio:
        fail(f"edge-tts returned no audio for {voice}")
    destination.write_bytes(audio)
    return {"words": words, "duration": round(probe_duration(destination), 3)}


def narrations_from_story(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 4:
        fail("story package needs exactly four scenes")
    lines = []
    for index, scene in enumerate(scenes, start=1):
        text = scene.get("narration") if isinstance(scene, dict) else None
        if not isinstance(text, str) or not text.strip():
            fail(f"scene {index} has no narration")
        lines.append(text.strip())
    return lines


async def render_pass(edge_tts, lines: list[str], voice: str, rate: str, out_dir: Path) -> list[dict]:
    scenes = []
    for index, text in enumerate(lines, start=1):
        destination = out_dir / f"scene-{index:02d}.mp3"
        spoken = await synthesize(edge_tts, text, voice, rate, destination)
        scenes.append(
            {
                "number": index,
                "narration": text,
                "audio": str(destination),
                "duration": spoken["duration"],
                "words": spoken["words"],
            }
        )
    return scenes


def choose_next_rate(current: int, speech: float, desired: float, seen: set[int]) -> int | None:
    if speech <= 0:
        return None
    speed = (1 + current / 100) * (speech / desired)
    nxt = max(-15, min(30, int(round((speed - 1) * 100))))
    if nxt == current or nxt in seen:
        return None
    return nxt


async def main_async(args: argparse.Namespace) -> None:
    voice = args.voice
    if "espeak" in voice.lower():
        fail("espeak-ng is not a fallback; use an Edge neural voice")
    edge_tts = load_edge_tts()
    lines = narrations_from_story(args.story)
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    overlaps = (len(lines) - 1) * args.transition
    desired_speech = args.target + overlaps
    percent = rate_percent(args.rate)
    seen: set[int] = set()
    attempts = []
    scenes: list[dict] = []
    for _ in range(6):
        seen.add(percent)
        rate = format_rate(percent)
        scenes = await render_pass(edge_tts, lines, voice, rate, out_dir)
        speech = round(sum(scene["duration"] for scene in scenes), 3)
        estimated_final = round(speech - overlaps, 3)
        attempts.append({"rate": rate, "speech_seconds": speech, "estimated_final_seconds": estimated_final})
        if args.min_seconds <= estimated_final <= args.max_seconds:
            break
        nxt = choose_next_rate(percent, speech, desired_speech, seen)
        if nxt is None:
            fail(
                "could not fit Farid narration into "
                f"{args.min_seconds:.0f}–{args.max_seconds:.0f}s at a natural rate. "
                f"Last estimate was {estimated_final}s at {rate}. Shorten the narration. "
                "espeak-ng will not be used."
            )
        percent = nxt
    else:
        fail("rate search did not converge")
    speech = attempts[-1]["speech_seconds"]
    manifest = {
        "engine": "edge-tts",
        "provider": "Microsoft Edge neural TTS",
        "voice": voice,
        "rate": attempts[-1]["rate"],
        "pitch": "+0Hz",
        "volume": "+0%",
        "espeak_used": False,
        "transition_seconds": args.transition,
        "target_final_seconds": args.target,
        "speech_seconds": speech,
        "estimated_final_seconds": attempts[-1]["estimated_final_seconds"],
        "attempts": attempts,
        "scenes": scenes,
    }
    (out_dir / "voice_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"voice": voice, "rate": manifest["rate"], "speech_seconds": speech, "estimated_final_seconds": manifest["estimated_final_seconds"]}, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Speak a four-scene Persian Reel with Edge TTS")
    parser.add_argument("--story", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--target", type=float, default=40.0)
    parser.add_argument("--min-seconds", type=float, default=38.0)
    parser.add_argument("--max-seconds", type=float, default=42.0)
    parser.add_argument("--transition", type=float, default=0.4)
    return parser.parse_args()


if __name__ == "__main__":
    if shutil.which("ffprobe") is None:
        fail("ffprobe is required to measure narration duration")
    asyncio.run(main_async(parse_args()))
