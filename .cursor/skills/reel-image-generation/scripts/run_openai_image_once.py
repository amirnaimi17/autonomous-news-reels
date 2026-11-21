#!/usr/bin/env python3
"""Send the one approved Sunburst image. No retries and no second image."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "reel-cost-tracking" / "scripts"))

from costing import authorize_image_test, record  # noqa: E402
from openai_images import PaidCallRefused, _urllib_transport, generate, image_request  # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
PACKAGE = ROOT / "storage/generated/pilot/20261119-07300041-api-quality/openai-image-test.json"
OUT_DIR = PACKAGE.parent
IMAGE_PATH = OUT_DIR / "openai-sunburst-1024x1536-high.png"
RESULT_PATH = OUT_DIR / "openai-image-result.json"
LEDGER = ROOT / "storage/cost-ledger/usage.jsonl"
RATES = {"image_output": 30.0, "text_input": 5.0, "image_input": 8.0}


def load_key() -> None:
    if os.environ.get("OPENAI_API_KEY"):
        return
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENAI_API_KEY="):
            os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
            return


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
    if IMAGE_PATH.exists():
        raise SystemExit("The OpenAI test image already exists. No second request will be sent.")
    load_key()
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))
    saved = package["request"]["body"]
    built = image_request(saved["prompt"])["body"]
    if built != saved:
        raise SystemExit("The rebuilt request does not match the approved prompt. No request will be sent.")
    text_tokens = int(package["text_tokenizer"]["text_input_tokens"])
    decision = authorize_image_test(
        text_input_tokens=text_tokens,
        image_input_tokens=0,
        ledger_path=LEDGER,
        month="2026-11",
    )
    if not decision["decision"]["allowed"]:
        raise SystemExit("Cost gate refused the image: " + "; ".join(decision["decision"]["reasons"]))
    timing = {"seconds": None}

    def timed_transport(spec: dict, api_key: str) -> bytes:
        started = time.perf_counter()
        try:
            return _urllib_transport(spec, api_key)
        finally:
            timing["seconds"] = round(time.perf_counter() - started, 3)

    try:
        result = generate(
            approved=True,
            prompt=saved["prompt"],
            text_input_tokens=text_tokens,
            image_input_tokens=0,
            ledger_path=LEDGER,
            out_path=IMAGE_PATH,
            transport=timed_transport,
        )
    except PaidCallRefused as error:
        RESULT_PATH.write_text(
            json.dumps({"sent": True, "retries": 0, "error": str(error), "image_written": False}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        raise SystemExit(str(error)) from None
    elapsed = timing["seconds"]
    raw = IMAGE_PATH.read_bytes()
    width, height = png_size(raw)
    usage = result["usage"]
    usd = calculated_usd(usage)
    record(
        LEDGER,
        {
            "reel_id": "openai-image-test-20261119",
            "provider": "openai",
            "model": saved["model"],
            "usd": usd,
            "cost_kind": "actual",
            "image_output_tokens": usage["image_output_tokens"],
            "text_input_tokens": usage["text_input_tokens"],
            "image_input_tokens": usage["image_input_tokens"],
            "allowed": True,
            "attempts": 1,
        },
    )
    report = {
        "sent": True,
        "retries": 0,
        "path": str(IMAGE_PATH),
        "bytes": len(raw),
        "width": width,
        "height": height,
        "duration_seconds": elapsed,
        "prompt": saved["prompt"],
        "request": saved,
        "usage": usage,
        "calculated_usd": usd,
        "rate_basis": "Published token rates applied to the response usage. This is not a separate invoice.",
        "estimate_usd": decision["estimate"]["estimated_usd"],
        "budget_guaranteed": False,
    }
    RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("path", "width", "height", "duration_seconds", "usage", "calculated_usd", "estimate_usd")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
