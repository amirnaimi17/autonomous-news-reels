#!/usr/bin/env python3
"""Eleven v4 speech requests. Listing and synthesis stay closed until approved."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MODEL_ID = "eleven_v4"
LANGUAGE_CODE = "fa"
OUTPUT_FORMAT = "mp3_44100_128"
API_ORIGIN = "https://api.elevenlabs.io"
ENV_NAME = "ELEVENLABS_API_KEY"
COST_ROOT = Path(__file__).resolve().parents[2] / "reel-cost-tracking"
LEDGER = Path(__file__).resolve().parents[4] / "storage" / "cost-ledger" / "usage.jsonl"


class PaidCallRefused(RuntimeError):
    """The speech request was not sent."""


def redact(text: str, secret: str | None) -> str:
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text


def speech_request(text: str, voice_id: str) -> dict:
    """Build the documented convert call. The API key is not part of this object."""

    spoken = text.strip()
    if not spoken:
        raise PaidCallRefused("The spoken text is empty.")
    if not voice_id or any(character in voice_id for character in "/?#& "):
        raise PaidCallRefused("A voice_id from the account or shared library is required.")
    return {
        "method": "POST",
        "url": f"{API_ORIGIN}/v1/text-to-speech/{urllib.parse.quote(voice_id, safe='')}",
        "query": {"output_format": OUTPUT_FORMAT},
        "body": {
            "text": spoken,
            "model_id": MODEL_ID,
            "language_code": LANGUAGE_CODE,
            "apply_text_normalization": "off",
            "voice_settings": {"speed": 1.0, "style": 0},
        },
    }


def account_voices_request(*, language: str = LANGUAGE_CODE, page_size: int = 100) -> dict:
    return {
        "method": "GET",
        "url": f"{API_ORIGIN}/v2/voices",
        "query": {
            "language": language,
            "page_size": page_size,
            "include_total_count": "false",
        },
    }


def shared_voices_request(*, language: str = LANGUAGE_CODE, search: str = "narration", page_size: int = 30) -> dict:
    """Shared library search. Premade English voices are not a Persian shortlist."""

    return {
        "method": "GET",
        "url": f"{API_ORIGIN}/v1/shared-voices",
        "query": {
            "language": language,
            "search": search,
            "page_size": page_size,
            "page": 0,
        },
    }


def public_voice(row: dict) -> dict:
    """Keep the fields needed to choose a voice. Drop everything else."""

    return {
        "voice_id": row.get("voice_id"),
        "name": row.get("name"),
        "language": row.get("language") or (row.get("labels") or {}).get("language"),
        "category": row.get("category"),
        "use_case": row.get("use_case") or (row.get("labels") or {}).get("use_case"),
        "accent": row.get("accent") or (row.get("labels") or {}).get("accent"),
        "locale": row.get("locale") or (row.get("labels") or {}).get("locale"),
        "verified_languages": _verified_languages(row),
        "preview_url": row.get("preview_url"),
        "preview_available": bool(row.get("preview_url")),
        "fiat_rate_usd_per_1000_credits": row.get("fiat_rate"),
        "rate_multiplier": row.get("rate"),
        "description": row.get("description"),
    }


def _verified_languages(row: dict) -> list[dict]:
    languages = []
    for item in row.get("verified_languages") or []:
        if isinstance(item, dict):
            languages.append(
                {
                    "language": item.get("language"),
                    "locale": item.get("locale"),
                    "model_id": item.get("model_id"),
                    "preview_url": item.get("preview_url"),
                }
            )
        elif isinstance(item, str):
            languages.append({"language": item})
    return languages


def supports_persian(voice: dict) -> bool:
    codes = {"fa", "fas", "per", "persian"}
    values = [voice.get("language"), voice.get("locale")]
    values.extend(item.get("language") for item in voice.get("verified_languages") or [])
    values.extend(item.get("locale") for item in voice.get("verified_languages") or [])
    return any(str(value or "").lower() in codes or str(value or "").lower().startswith("fa") for value in values)


def _api_key() -> str:
    key = os.environ.get(ENV_NAME, "")
    if not key:
        raise PaidCallRefused(f"{ENV_NAME} is unset. No request will be sent.")
    return key


SAFE_RESPONSE_HEADERS = ("character-cost", "request-id", "history-item-id")


def _safe_headers(headers) -> dict:
    found = {}
    for name, value in headers.items():
        if name.lower() in SAFE_RESPONSE_HEADERS:
            found[name.lower()] = value
    return found


def _send(spec: dict, api_key: str, transport) -> bytes:
    body, _headers = _exchange(spec, api_key, transport)
    return body


def _exchange(spec: dict, api_key: str, transport) -> tuple[bytes, dict]:
    if transport is None:
        transport = _urllib_exchange
    try:
        result = transport(spec, api_key)
    except Exception as error:
        raise PaidCallRefused(redact(str(error), api_key)) from None
    if isinstance(result, tuple):
        body, headers = result
        return body, dict(headers)
    return result, {}


def _urllib_transport(spec: dict, api_key: str) -> bytes:
    body, _headers = _urllib_exchange(spec, api_key)
    return body


def _urllib_exchange(spec: dict, api_key: str) -> tuple[bytes, dict]:
    query = urllib.parse.urlencode(spec.get("query") or {})
    url = spec["url"] + (("?" + query) if query else "")
    data = None
    headers = {"xi-api-key": api_key, "Accept": "application/json"}
    if spec["method"] == "POST":
        data = json.dumps(spec["body"]).encode("utf-8")
        headers["Content-Type"] = "application/json"
        headers["Accept"] = "audio/mpeg"
    request = urllib.request.Request(url, data=data, headers=headers, method=spec["method"])
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return response.read(), _safe_headers(response.headers)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        receipt = _safe_headers(error.headers)
        message = f"ElevenLabs returned HTTP {error.code}: {redact(detail, api_key)}"
        if receipt:
            message = f"{message} | receipt={json.dumps(receipt, ensure_ascii=False)}"
        raise PaidCallRefused(message) from None


def list_voices(spec: dict, *, approve_list: bool = False, transport=None) -> dict:
    if not approve_list:
        raise PaidCallRefused("Voice listing was not approved. Pass approve_list only after the key is configured.")
    payload = _send(spec, _api_key(), transport)
    body = json.loads(payload.decode("utf-8"))
    voices = [public_voice(row) for row in body.get("voices", [])]
    return {
        "voices": voices,
        "has_more": bool(body.get("has_more")),
        "next_page_token": body.get("next_page_token"),
    }


def synthesize(
    text: str,
    voice_id: str,
    *,
    approved: bool = False,
    voice_rate_confirmed: bool = False,
    voice_fiat_rate_per_1000: float | None = None,
    ledger_path: Path | None = None,
    out_path: Path | None = None,
    transport=None,
) -> bytes:
    """Send one speech request only when the user and the voice cost gate both allow it."""

    if not approved:
        raise PaidCallRefused("Paid speech was not approved.")
    _load_costing()
    from costing import authorize_voice_test  # noqa: WPS433

    characters = len(text.strip())
    decision = authorize_voice_test(
        characters=characters,
        voice_rate_confirmed=voice_rate_confirmed,
        voice_fiat_rate_per_1000=voice_fiat_rate_per_1000,
        ledger_path=LEDGER if ledger_path is None else ledger_path,
    )
    if not decision["decision"]["allowed"]:
        raise PaidCallRefused("Cost gate refused the experiment: " + "; ".join(decision["decision"]["reasons"]))
    audio = _send(speech_request(text, voice_id), _api_key(), transport)
    if not audio.startswith(b"ID3") and not audio.startswith(b"\xff"):
        raise PaidCallRefused("ElevenLabs did not return MP3 audio.")
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(audio)
    return audio


def speak_with_receipt(
    text: str,
    voice_id: str,
    *,
    approved: bool = False,
    voice_rate_confirmed: bool = False,
    voice_fiat_rate_per_1000: float | None = None,
    spent_usd: float = 0.0,
    max_usd: float = 0.06,
    ledger_path: Path | None = None,
    transport=None,
) -> dict:
    """Send one speech request. The caller must not loop over a failure."""

    if not approved:
        raise PaidCallRefused("Paid speech was not approved.")
    _load_costing()
    from costing import authorize_voice_test  # noqa: WPS433

    decision = authorize_voice_test(
        characters=len(text.strip()),
        voice_rate_confirmed=voice_rate_confirmed,
        voice_fiat_rate_per_1000=voice_fiat_rate_per_1000,
        ledger_path=LEDGER if ledger_path is None else ledger_path,
    )
    if not decision["decision"]["allowed"]:
        raise PaidCallRefused("Cost gate refused the voice test: " + "; ".join(decision["decision"]["reasons"]))
    estimate = float(decision["estimate"]["estimated_usd"])
    if spent_usd + estimate > max_usd:
        raise PaidCallRefused(
            f"This sample estimate ${estimate:.5f} plus ${spent_usd:.5f} already committed exceeds the ${max_usd:.2f} experiment cap."
        )
    audio, headers = _exchange(speech_request(text, voice_id), _api_key(), transport)
    if not audio.startswith(b"ID3") and not audio.startswith(b"\xff"):
        raise PaidCallRefused("ElevenLabs did not return MP3 audio.")
    return {"audio": audio, "headers": headers, "estimated_usd": estimate}


def _load_costing() -> None:
    import sys

    scripts = str(COST_ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)


def main() -> None:
    _load_costing()
    parser = argparse.ArgumentParser(description="Prepare or, after approval, call Eleven v4")
    sub = parser.add_subparsers(dest="command", required=True)
    shared = sub.add_parser("list-shared")
    shared.add_argument("--language", default=LANGUAGE_CODE)
    shared.add_argument("--search", default="narration")
    shared.add_argument("--approve-list", action="store_true")
    account = sub.add_parser("list-account")
    account.add_argument("--language", default=LANGUAGE_CODE)
    account.add_argument("--approve-list", action="store_true")
    args = parser.parse_args()
    if args.command == "list-shared":
        spec = shared_voices_request(language=args.language, search=args.search)
    else:
        spec = account_voices_request(language=args.language)
    if not args.approve_list:
        print(json.dumps({"sent": False, "request": spec}, ensure_ascii=False, indent=2))
        raise SystemExit(2)
    print(json.dumps(list_voices(spec, approve_list=True), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
