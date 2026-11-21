#!/usr/bin/env python3
"""OpenAI image generations. The paid call stays closed until the token price is known."""

from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

MODEL_ID = "gpt-image-2.5-sunburst"
SIZE = "1024x1536"
QUALITY = "high"
API_URL = "https://api.openai.com/v1/images/generations"
MODEL_URL = "https://api.openai.com/v1/models/gpt-image-2.5-sunburst"
ENV_NAME = "OPENAI_API_KEY"
COST_SCRIPTS = Path(__file__).resolve().parents[2] / "reel-cost-tracking" / "scripts"
LEDGER = Path(__file__).resolve().parents[4] / "storage" / "cost-ledger" / "usage.jsonl"

IMAGE_PROMPT = (
    "Flat editorial illustration in a vertical frame. Navy, warm paper, muted blue, and muted red. "
    "Simple geometric benches in an empty assembly hall, with more blue shapes than red shapes. "
    "No people, no faces, no hands, no letters, no numbers, no logos, no captions, and no photograph."
)

ALASKA_TEST_PROMPT = (
    "Photorealistic cinematic vertical photograph. Keep the glass legislative hall, warm interior light, "
    "snow-covered spruce, and dark mountains centered so they remain visible in a taller crop. "
    "Blue hour in a northern coastal capital, professional editorial lighting, sharp detail, "
    "premium news-magazine atmosphere. No people, no faces, no hands, no letters, no numbers, "
    "no logos, no watermarks, and no captions."
)


class PaidCallRefused(RuntimeError):
    """The image request was not sent."""


def redact(text: str, secret: str | None) -> str:
    if not secret:
        return text
    return text.replace(secret, "[redacted]").replace(f"Bearer {secret}", "Bearer [redacted]")


def image_request(prompt: str = IMAGE_PROMPT) -> dict:
    """Build the documented Images API call. Authorization is not part of this object."""

    cleaned = " ".join(prompt.split())
    if not cleaned:
        raise PaidCallRefused("The image prompt is empty.")
    if any(character.isdigit() for character in cleaned):
        raise PaidCallRefused("The illustration prompt must not contain digits that the model can paint as text.")
    return {
        "method": "POST",
        "url": API_URL,
        "body": {
            "model": MODEL_ID,
            "prompt": cleaned,
            "size": SIZE,
            "quality": QUALITY,
            "output_format": "png",
            "background": "opaque",
            "n": 1,
        },
    }


def model_probe_request() -> dict:
    """A read of the model record. This is not an image generation."""

    return {"method": "GET", "url": MODEL_URL}


def probe_model(*, transport=None) -> dict:
    if transport is None:
        transport = _urllib_get
    try:
        payload = transport(model_probe_request(), _api_key())
    except PaidCallRefused:
        raise
    except Exception as error:
        raise PaidCallRefused(redact(str(error), os.environ.get(ENV_NAME))) from None
    body = json.loads(payload.decode("utf-8"))
    return {"id": body.get("id"), "owned_by": body.get("owned_by"), "available": body.get("id") == MODEL_ID}


def _urllib_get(spec: dict, api_key: str) -> bytes:
    if spec.get("method") != "GET" or spec.get("url") != MODEL_URL:
        raise PaidCallRefused("The model probe can only read the model record.")
    request = urllib.request.Request(
        spec["url"],
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise PaidCallRefused(f"OpenAI returned HTTP {error.code}: {redact(detail, api_key)}") from None


def tokens_from_usage(usage: dict) -> dict:
    """Read the response usage object. Missing token fields stay unpriced."""

    details = usage.get("input_tokens_details")
    if not isinstance(details, dict) or "output_tokens" not in usage or "text_tokens" not in details or "image_tokens" not in details:
        raise PaidCallRefused("The usage object did not include image output tokens and text input tokens.")
    return {
        "image_output_tokens": int(usage["output_tokens"]),
        "text_input_tokens": int(details["text_tokens"]),
        "image_input_tokens": int(details["image_tokens"]),
    }


def _api_key() -> str:
    key = os.environ.get(ENV_NAME, "")
    if not key:
        raise PaidCallRefused(f"{ENV_NAME} is unset. No request will be sent.")
    return key


def _urllib_transport(spec: dict, api_key: str) -> bytes:
    request = urllib.request.Request(
        spec["url"],
        data=json.dumps(spec["body"]).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise PaidCallRefused(f"OpenAI returned HTTP {error.code}: {redact(detail, api_key)}") from None


def generate(
    *,
    approved: bool = False,
    prompt: str = IMAGE_PROMPT,
    image_output_tokens: int | None = None,
    text_input_tokens: int | None = None,
    image_input_tokens: int | None = None,
    ledger_path: Path | None = None,
    out_path: Path | None = None,
    transport=None,
) -> dict:
    """Send one image request only when its own token quote is allowed."""

    if not approved:
        raise PaidCallRefused("Paid image generation was not approved.")
    if str(COST_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(COST_SCRIPTS))
    from costing import authorize_image_test  # noqa: WPS433

    decision = authorize_image_test(
        image_output_tokens=image_output_tokens,
        text_input_tokens=text_input_tokens,
        image_input_tokens=image_input_tokens,
        ledger_path=LEDGER if ledger_path is None else ledger_path,
    )
    if not decision["decision"]["allowed"]:
        raise PaidCallRefused("Cost gate refused the experiment: " + "; ".join(decision["decision"]["reasons"]))
    if transport is None:
        transport = _urllib_transport
    spec = image_request(prompt)
    try:
        payload = transport(spec, _api_key())
    except PaidCallRefused:
        raise
    except Exception as error:
        raise PaidCallRefused(redact(str(error), os.environ.get(ENV_NAME))) from None
    body = json.loads(payload.decode("utf-8"))
    encoded = body.get("data", [{}])[0].get("b64_json")
    if not encoded:
        raise PaidCallRefused("OpenAI did not return image data.")
    raw = base64.b64decode(encoded)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(raw)
    return {"usage": tokens_from_usage(body.get("usage") or {}), "image_bytes": len(raw)}
