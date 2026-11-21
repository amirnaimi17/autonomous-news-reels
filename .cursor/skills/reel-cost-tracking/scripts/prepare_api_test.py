#!/usr/bin/env python3
"""Write the unpaid API quality-test package. This does not call a provider."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
IMAGE_SCRIPTS = Path(__file__).resolve().parents[2] / "reel-image-generation" / "scripts"
sys.path.insert(0, str(IMAGE_SCRIPTS))

from costing import authorize_image_test, authorize_voice_test  # noqa: E402
from openai_images import IMAGE_PROMPT, image_request  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
DEFAULT_SPOKEN = ROOT / "storage/generated/pilot/20261119-07300041-narration-compare/narration-spoken.txt"
DEFAULT_DISPLAY = ROOT / "storage/generated/pilot/20261119-07300041-narration-compare/narration-display.txt"
DEFAULT_OUT = ROOT / "storage/generated/pilot/20261119-07300041-api-quality"
LEDGER = ROOT / "storage/cost-ledger/usage.jsonl"


def write_package(spoken_path: Path, display_path: Path, out_dir: Path) -> dict:
    spoken = spoken_path.read_text(encoding="utf-8").strip()
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(spoken_path, out_dir / "narration-spoken.txt")
    if display_path.exists():
        shutil.copyfile(display_path, out_dir / "narration-display.txt")
    voice_pending = authorize_voice_test(
        characters=len(spoken),
        voice_rate_confirmed=False,
        ledger_path=LEDGER,
        month="2026-11",
    )
    voice_default_rate = authorize_voice_test(
        characters=len(spoken),
        voice_rate_confirmed=True,
        ledger_path=LEDGER,
        month="2026-11",
    )
    image = authorize_image_test(ledger_path=LEDGER, month="2026-11")
    package = {
        "sent": False,
        "characters": len(spoken),
        "reference_edge_duration_seconds": 17.208,
        "duration_window_seconds": [15, 20],
        "duration_note": "17.208 seconds is the measured Edge Farid reading of this text at rate +0%. ElevenLabs duration is not measured, and the speed stays at 1.0.",
        "speech_request_without_voice_id": {
            "method": "POST",
            "url": "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            "query": {"output_format": "mp3_44100_128"},
            "body": {
                "text": spoken,
                "model_id": "eleven_v4",
                "language_code": "fa",
                "apply_text_normalization": "off",
                "voice_settings": {"speed": 1.0, "style": 0},
            },
        },
        "image_request": image_request(IMAGE_PROMPT),
        "voice_authorization_pending_rate": voice_pending,
        "voice_authorization_default_rate": voice_default_rate,
        "image_authorization": image,
    }
    (out_dir / "api-test-package.json").write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return package


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare the unpaid ElevenLabs and OpenAI quality test")
    parser.add_argument("--spoken", type=Path, default=DEFAULT_SPOKEN)
    parser.add_argument("--display", type=Path, default=DEFAULT_DISPLAY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    package = write_package(args.spoken, args.display, args.out_dir)
    print(
        json.dumps(
            {
                "out_dir": str(args.out_dir),
                "characters": package["characters"],
                "voice_default_rate_allowed": package["voice_authorization_default_rate"]["decision"]["allowed"],
                "image_allowed": package["image_authorization"]["decision"]["allowed"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if package["image_authorization"]["decision"]["allowed"]:
        raise SystemExit("The image test must stay blocked until its output tokens are known.")


if __name__ == "__main__":
    main()
