#!/usr/bin/env python3
"""Generate the three approved Alaska scenes. One request each, no retries."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "reel-cost-tracking" / "scripts"))

from costing import authorize_plan, image_request as priced_image, record  # noqa: E402
from openai_images import PaidCallRefused, _urllib_transport, generate  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT / "storage/generated/pilot/20261119-07300041-aran-three"
LEDGER = ROOT / "storage/cost-ledger/usage.jsonl"
RATES = {"image_output": 30.0, "text_input": 5.0, "image_input": 8.0}
STYLE = (
    "Photorealistic cinematic vertical photograph of one continuous place: a curved glass legislative hall "
    "in a northern coastal capital at blue hour. Warm interior light, snow-covered spruce, dark mountains, "
    "and calm dark water. Professional editorial photography, strong cinematic composition, sharp detail, "
    "premium news-magazine atmosphere. Keep the subject centered so it remains visible in a taller crop. "
    "No people, no faces, no hands, no letters, no numbers, no logos, no watermarks, and no captions. "
)
SCENES = [
    {
        "number": 1,
        "beat": "The Associated Press race call, shown as the hall itself.",
        "prompt": STYLE + "Wide view from the snowy shore: the glowing curved hall sits between spruce trees and the water, with the mountains filling the background.",
    },
    {
        "number": 2,
        "beat": "The close first-choice result, shown without printed figures.",
        "prompt": STYLE + "Inside that same hall, a long wooden counting table holds two unmarked stacks of blank paper, one stack slightly taller, and the glass wall opens onto the snow and mountains.",
    },
    {
        "number": 3,
        "beat": "The result is not yet official.",
        "prompt": STYLE + "Inside that same hall, an empty wooden desk holds a closed plain folder and a sealed plain envelope, the lights still warm, with snow and mountains beyond the glass.",
    },
]


def load_key() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return


def text_tokens(prompt: str) -> int:
    site = Path("/tmp/token-venv/lib/python3.14/site-packages")
    sys.path.insert(0, str(site))
    import tiktoken

    return len(tiktoken.get_encoding("o200k_base").encode(prompt))


def png_size(data: bytes) -> tuple[int, int]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PaidCallRefused("OpenAI did not return a PNG.")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def calculated_usd(usage: dict) -> float:
    return round(
        (
            usage["image_output_tokens"] * RATES["image_output"]
            + usage["text_input_tokens"] * RATES["text_input"]
            + usage["image_input_tokens"] * RATES["image_input"]
        )
        / 1_000_000,
        6,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    if any((OUT / f"scene-{scene['number']:02d}.png").exists() for scene in SCENES):
        raise SystemExit("A scene image already exists. No additional request will be sent.")
    load_key()
    requests = []
    for scene in SCENES:
        if any(character.isdigit() for character in scene["prompt"]):
            raise SystemExit(f"Scene {scene['number']} prompt contains a digit. No request will be sent.")
        scene["text_input_tokens"] = text_tokens(scene["prompt"])
        requests.append(priced_image(text_input_tokens=scene["text_input_tokens"], image_input_tokens=0))
    decision = authorize_plan(
        {"reel_id": "aran-three-20261119", "requests": requests},
        ledger_path=LEDGER,
        month="2026-11",
    )
    (OUT / "image-authorization.json").write_text(json.dumps(decision, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not decision["decision"]["allowed"]:
        raise SystemExit("Cost gate refused the three images: " + "; ".join(decision["decision"]["reasons"]))
    results = []
    for scene in SCENES:
        destination = OUT / f"scene-{scene['number']:02d}.png"
        timing = {"seconds": None}

        def timed_transport(spec: dict, api_key: str, clock=timing) -> bytes:
            started = time.perf_counter()
            try:
                return _urllib_transport(spec, api_key)
            finally:
                clock["seconds"] = round(time.perf_counter() - started, 3)

        try:
            generated = generate(
                approved=True,
                prompt=scene["prompt"],
                text_input_tokens=scene["text_input_tokens"],
                image_input_tokens=0,
                ledger_path=LEDGER,
                out_path=destination,
                transport=timed_transport,
            )
        except PaidCallRefused as error:
            failure = {"scene": scene["number"], "sent": True, "retries": 0, "error": str(error), "image_written": destination.exists()}
            (OUT / "image-results.json").write_text(json.dumps({"completed": results, "failure": failure}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"Scene {scene['number']} failed and was not retried: {error}") from None
        raw = destination.read_bytes()
        width, height = png_size(raw)
        usage = generated["usage"]
        usd = calculated_usd(usage)
        record(
            LEDGER,
            {
                "reel_id": "aran-three-20261119",
                "provider": "openai",
                "model": "gpt-image-2.5-sunburst",
                "scene": scene["number"],
                "usd": usd,
                "cost_kind": "actual",
                "image_output_tokens": usage["image_output_tokens"],
                "text_input_tokens": usage["text_input_tokens"],
                "image_input_tokens": usage["image_input_tokens"],
                "allowed": True,
                "attempts": 1,
            },
        )
        results.append(
            {
                "scene": scene["number"],
                "beat": scene["beat"],
                "path": str(destination),
                "bytes": len(raw),
                "width": width,
                "height": height,
                "duration_seconds": timing["seconds"],
                "prompt": scene["prompt"],
                "usage": usage,
                "calculated_usd": usd,
                "retries": 0,
            }
        )
        print(json.dumps({"scene": scene["number"], "width": width, "height": height, "seconds": timing["seconds"], "usd": usd, "usage": usage}, ensure_ascii=False), flush=True)
    (OUT / "image-results.json").write_text(
        json.dumps(
            {
                "images": 3,
                "retries": 0,
                "estimate_usd": decision["estimate"]["estimated_usd"],
                "calculated_usd": round(sum(item["calculated_usd"] for item in results), 6),
                "budget_guaranteed": False,
                "scenes": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
