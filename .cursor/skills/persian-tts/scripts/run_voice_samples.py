#!/usr/bin/env python3
"""Generate three approved Eleven v4 samples. One attempt each, capped at $0.06."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
COST_SCRIPTS = Path(__file__).resolve().parents[2] / "reel-cost-tracking" / "scripts"
sys.path.insert(0, str(COST_SCRIPTS))

from costing import record  # noqa: E402
from elevenlabs import PaidCallRefused, speak_with_receipt  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
SPOKEN_PATH = ROOT / "storage/generated/pilot/20261119-07300041-api-quality/narration-spoken.txt"
OUT_DIR = ROOT / "storage/generated/pilot/20261119-07300041-elevenlabs-voice-test"
LEDGER = ROOT / "storage/cost-ledger/usage.jsonl"
MAX_USD = 0.06
CATALOG_PER_CHARACTER = 0.00008
VOICES = (
    ("arash", "Arash", "Mn0jJ3FC9Ijz7lQe8ELI"),
    ("connery", "Connery", "4D8rX5FMrycxXbF6iW0I"),
    ("aran", "Aran", "PEdcOLzbXYhL8IKOswXB"),
)


def load_key() -> None:
    if os.environ.get("ELEVENLABS_API_KEY"):
        return
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            os.environ["ELEVENLABS_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return


def duration_seconds(path: Path) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        return round(float(result.stdout.strip()), 3)
    except ValueError:
        return None


def usd_from_header(headers: dict, estimate: float) -> tuple[float, str, int | None]:
    raw = headers.get("character-cost")
    if raw is None:
        return estimate, "estimate", None
    characters = int(raw)
    return round(characters * CATALOG_PER_CHARACTER, 6), "actual", characters


def main() -> None:
    load_key()
    spoken = SPOKEN_PATH.read_text(encoding="utf-8").strip()
    if len(spoken) != 216:
        raise SystemExit(f"The narration is {len(spoken)} characters, not the approved 216.")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    spent = 0.0
    rows = []
    for slug, name, voice_id in VOICES:
        row = {
            "name": name,
            "file": f"{slug}.mp3",
            "provider": "elevenlabs",
            "model": "eleven_v4",
            "language_code": "fa",
            "voice_id": voice_id,
            "characters_sent": len(spoken),
            "speed": 1.0,
            "text_sha256": hashlib.sha256(spoken.encode("utf-8")).hexdigest(),
        }
        try:
            result = speak_with_receipt(
                spoken,
                voice_id,
                approved=True,
                voice_rate_confirmed=True,
                spent_usd=spent,
                max_usd=MAX_USD,
                ledger_path=LEDGER,
            )
        except PaidCallRefused as error:
            row["error"] = str(error)
            row["attempts"] = 1
            rows.append(row)
            continue
        audio = result["audio"]
        path = OUT_DIR / f"{slug}.mp3"
        path.write_bytes(audio)
        usd, kind, billed_characters = usd_from_header(result["headers"], result["estimated_usd"])
        spent = round(spent + usd, 6)
        row.update(
            {
                "bytes": len(audio),
                "duration_seconds": duration_seconds(path),
                "character_cost": billed_characters,
                "request_id": result["headers"].get("request-id"),
                "history_item_id": result["headers"].get("history-item-id"),
                "usd": usd,
                "cost_kind": kind,
                "attempts": 1,
                "error": None,
            }
        )
        record(
            LEDGER,
            {
                "reel_id": "elevenlabs-voice-test-20261119",
                "provider": "elevenlabs",
                "model": "eleven_v4",
                "voice_id": voice_id,
                "usd": usd,
                "cost_kind": kind,
                "characters": billed_characters if billed_characters is not None else len(spoken),
                "request_id": result["headers"].get("request-id"),
                "allowed": True,
            },
        )
        rows.append(row)
        if spent > MAX_USD:
            break
    report = {
        "experiment_max_usd": MAX_USD,
        "spent_usd": spent,
        "speech_requests": len(rows),
        "retries": 0,
        "samples": rows,
    }
    (OUT_DIR / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# ElevenLabs Persian voice test",
        "",
        f"Authorized cap: ${MAX_USD:.2f}. Recorded spend: ${spent:.5f}. Retries: 0.",
        "",
        "The spoken text was the same 216-character Alaska passage for every request.",
        "",
    ]
    for row in rows:
        lines.append(f"## {row['name']}")
        lines.append("")
        lines.append(f"- File: `{row['file']}`")
        lines.append(f"- Provider and model: {row['provider']} `{row['model']}`, language `{row['language_code']}`")
        lines.append(f"- Voice ID: `{row['voice_id']}`")
        if row.get("error"):
            lines.append(f"- Error: {row['error']}")
        else:
            lines.append(f"- Duration: {row['duration_seconds']} seconds")
            lines.append(f"- Character cost header: {row['character_cost']}")
            lines.append(f"- Cost: ${row['usd']:.6f} ({row['cost_kind']})")
            lines.append(f"- Request ID: `{row['request_id']}`")
        lines.append("")
    (OUT_DIR / "comparison-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"out_dir": str(OUT_DIR), "spent_usd": spent, "samples": [{k: row.get(k) for k in ("name", "duration_seconds", "usd", "cost_kind", "character_cost", "error")} for row in rows]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
