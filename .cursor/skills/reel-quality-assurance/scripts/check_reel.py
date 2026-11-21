#!/usr/bin/env python3
"""Technical checks for a rendered Reel. A pass is not a human quality review."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(result.stderr.strip() or f"ffprobe failed for {path}")
    return json.loads(result.stdout)


def volume(path: Path) -> dict:
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    found = {}
    for line in result.stderr.splitlines():
        if "max_volume:" in line:
            found["max_volume_db"] = float(line.rsplit(":", 1)[1].replace("dB", "").strip())
        if "mean_volume:" in line:
            found["mean_volume_db"] = float(line.rsplit(":", 1)[1].replace("dB", "").strip())
    return found


def black_frames(path: Path) -> list[str]:
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-vf", "blackdetect=d=0.2:pic_th=0.98", "-f", "null", "-"],
        check=False,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stderr.splitlines() if "black_start" in line]


def technical_checks(info: dict, levels: dict, blacks: list[str], *, min_seconds: float, max_seconds: float) -> list[dict]:
    video = next((stream for stream in info.get("streams", []) if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in info.get("streams", []) if stream.get("codec_type") == "audio"), None)
    duration = float(info.get("format", {}).get("duration") or 0)
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail, "kind": "technical"})

    add("file_decodes", video is not None, "ffprobe returned a video stream" if video else "no video stream")
    if video:
        rate = video.get("avg_frame_rate", "0/1")
        num, den = rate.split("/")
        fps = float(num) / float(den) if float(den) else 0
        add("resolution", video.get("width") == 1080 and video.get("height") == 1920, f"{video.get('width')}x{video.get('height')}")
        add("frame_rate", abs(fps - 30) < 0.2, f"{fps:.3f} fps")
        add("h264", video.get("codec_name") == "h264", str(video.get("codec_name")))
    add("duration", min_seconds <= duration <= max_seconds, f"{duration:.3f}s")
    add("audio_present", audio is not None and audio.get("codec_name") == "aac", str(None if audio is None else audio.get("codec_name")))
    if "max_volume_db" in levels:
        add("not_clipping", levels["max_volume_db"] < -0.5, f"peak {levels['max_volume_db']} dB")
        add("not_silent", levels.get("mean_volume_db", -99) > -45, f"mean {levels.get('mean_volume_db')} dB")
    else:
        add("not_clipping", False, "volumedetect returned no peak")
    add("no_long_black", not blacks, "; ".join(blacks) if blacks else "none")
    return checks


def contact_sheet(video: Path, times: list[float], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, stamp in enumerate(times, start=1):
        frame = destination.parent / f"frame-{index}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{stamp:.3f}", "-i", str(video), "-frames:v", "1", str(frame)],
            check=True,
            capture_output=True,
        )
        frames.append(frame)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            *sum((["-i", str(frame)] for frame in frames), []),
            "-filter_complex",
            f"hstack=inputs={len(frames)}",
            str(destination),
        ],
        check=True,
        capture_output=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Technical QA for one Reel")
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--images", type=Path, nargs=4, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--min-seconds", type=float, default=38)
    parser.add_argument("--max-seconds", type=float, default=42)
    args = parser.parse_args()
    missing = [str(path) for path in [args.video, args.manifest, *args.images] if not path.is_file()]
    info = probe(args.video) if args.video.is_file() else {}
    levels = volume(args.video) if args.video.is_file() else {}
    blacks = black_frames(args.video) if args.video.is_file() else []
    checks = technical_checks(info, levels, blacks, min_seconds=args.min_seconds, max_seconds=args.max_seconds) if info else []
    checks.append({"name": "assets_present", "ok": not missing, "detail": ", ".join(missing) or "all present", "kind": "technical"})
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest.is_file() else {}
    farid = manifest.get("voice") == "fa-IR-FaridNeural" and manifest.get("espeak_used") is False and manifest.get("rate") == "+0%"
    aran = (
        manifest.get("provider") == "elevenlabs"
        and manifest.get("model") == "eleven_v4"
        and manifest.get("voice_id") == "PEdcOLzbXYhL8IKOswXB"
        and manifest.get("language_code") == "fa"
        and manifest.get("speed") == 1.0
        and manifest.get("espeak_used") is not True
    )
    voice_ok = farid or aran
    checks.append({"name": "narration_voice", "ok": voice_ok, "detail": f"voice={manifest.get('voice') or manifest.get('voice_id')}", "kind": "technical"})
    duration = float(info.get("format", {}).get("duration") or 0)
    sheet = args.out.parent / "contact-sheet.jpg"
    if args.video.is_file() and duration > 0:
        stamps = [duration * 0.12, duration * 0.37, duration * 0.62, duration * 0.87]
        contact_sheet(args.video, stamps, sheet)
    report = {
        "technical_pass": all(item["ok"] for item in checks),
        "human_review": {
            "voice_naturalness": "not reviewed",
            "design_quality": "not reviewed",
            "note": "A technical pass does not mean the voice or the design passed human review.",
        },
        "checks": checks,
        "contact_sheet": str(sheet) if sheet.exists() else None,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"technical_pass": report["technical_pass"], "report": str(args.out)}, ensure_ascii=False))
    if not report["technical_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
