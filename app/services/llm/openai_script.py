"""OpenAI chat transport for Persian story packages.

Builds the documented Chat Completions request. The network call stays behind an
injectable transport so unit tests never spend money or touch the live API.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

from app.core.exceptions import ConfigurationError, GroundingError

API_URL = "https://api.openai.com/v1/chat/completions"
ENV_NAME = "OPENAI_API_KEY"
DEFAULT_MODEL = "gpt-4o-mini"

Transport = Callable[[dict[str, Any], str], bytes]


def redact(text: str, secret: str | None) -> str:
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text


# Strict JSON Schema for Chat Completions structured outputs (gpt-4o / gpt-4o-mini).
STORY_PACKAGE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    # OpenAI strict structured outputs require every property key to appear in
    # ``required`` (optional values use "" / empty arrays instead of omitted keys).
    "required": [
        "schema_version",
        "event_id",
        "language",
        "audience",
        "headline",
        "source_urls",
        "claims",
        "duration_seconds",
        "duration_policy",
        "scenes",
        "disclaimers",
    ],
    "properties": {
        "schema_version": {"type": "string", "enum": ["pilot-1"]},
        "event_id": {"type": "string", "minLength": 1},
        "language": {"type": "string", "minLength": 2},
        "audience": {"type": "string", "minLength": 1},
        "headline": {"type": "string", "minLength": 1},
        "source_urls": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 8},
        },
        "claims": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["text", "source_urls"],
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "source_urls": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "minLength": 8},
                    },
                },
            },
        },
        "duration_seconds": {"type": "number"},
        "duration_policy": {"type": "string"},
        "scenes": {
            "type": "array",
            "minItems": 3,
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "number",
                    "duration_seconds",
                    "narration",
                    "on_screen_text",
                    "visual_prompt",
                ],
                "properties": {
                    "number": {"type": "integer"},
                    "duration_seconds": {"type": "number"},
                    "narration": {"type": "string", "minLength": 1},
                    "on_screen_text": {"type": "string", "minLength": 1},
                    "visual_prompt": {"type": "string", "minLength": 8},
                },
            },
        },
        "disclaimers": {"type": "array", "items": {"type": "string"}},
    },
}


_DEFAULT_SCRIPT_SYSTEM = (
    "You are a news Reel scriptwriter. Reply with one JSON object only. "
    "The top-level key scenes MUST be a JSON array of 3–8 scene objects "
    "(never an object/map). Never invent facts outside the supplied fact pack. "
    "visual_prompt values must be English photograph search descriptions, "
    "not generic graphic or typography placeholders."
)

# Only these response-body markers justify falling back from json_schema to json_object.
_SCHEMA_COMPAT_MARKERS = (
    "response_format",
    "json_schema",
    "json schema",
    "structured outputs",
    "structured output",
    "invalid_schema",
    "invalid schema",
    "unknown parameter",
    "not supported with",
    "does not support",
    "unsupported parameter",
)


def is_schema_compatibility_error(status: int, detail: str) -> bool:
    """Return True only for confirmed structured-output / schema rejections."""

    if status not in {400, 404}:
        return False
    text = (detail or "").casefold()
    if not text:
        return False
    has_format_signal = any(
        marker in text
        for marker in ("response_format", "json_schema", "json schema", "structured output")
    )
    has_compat_signal = any(marker in text for marker in _SCHEMA_COMPAT_MARKERS)
    return has_format_signal and has_compat_signal


def chat_request(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    json_schema: dict[str, Any] | None = None,
    schema_name: str = "pilot_story_package",
    system_content: str | None = None,
    use_json_schema: bool | None = None,
) -> dict[str, Any]:
    """Build the Chat Completions body. The API key is never stored on this object.

    Pass ``json_schema`` for structured outputs. ``use_json_schema=True`` without a
    custom schema keeps the story-package schema for script callers. Ranking and
    other callers must pass their own schema (or ``use_json_schema=False``) so they
    are never constrained to the story-package shape.
    """

    spoken = prompt.strip()
    if not spoken:
        raise GroundingError("script prompt is empty")
    schema = json_schema
    # Default remains story-package structured output for script callers.
    schema_flag = True if use_json_schema is None and schema is None else use_json_schema
    if schema is None and schema_flag is True:
        schema = STORY_PACKAGE_JSON_SCHEMA
        schema_name = "pilot_story_package"
    if schema is not None:
        response_format: dict[str, Any] = {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }
        default_system = _DEFAULT_SCRIPT_SYSTEM
    else:
        response_format = {"type": "json_object"}
        default_system = "Reply with one JSON object only. Never invent facts outside the prompt."
    return {
        "method": "POST",
        "url": API_URL,
        "body": {
            "model": model,
            "temperature": 0.2,
            "response_format": response_format,
            "messages": [
                {
                    "role": "system",
                    "content": (system_content or default_system).strip(),
                },
                {"role": "user", "content": spoken},
            ],
        },
    }


def api_key_from_env() -> str:
    return os.environ.get(ENV_NAME, "").strip()


def complete_chat(
    prompt: str,
    context: Mapping[str, Any] | None = None,
    *,
    model: str | None = None,
    api_key: str | None = None,
    transport: Transport | None = None,
    json_schema: dict[str, Any] | None = None,
    schema_name: str = "pilot_story_package",
    system_content: str | None = None,
    use_json_schema: bool | None = None,
) -> dict[str, Any]:
    """Send or mock a chat completion and return the parsed assistant JSON object."""

    del context  # available for logging/adapters; never required for the request body
    key = (api_key if api_key is not None else api_key_from_env()).strip()
    if not key:
        raise ConfigurationError(f"{ENV_NAME} is required for OpenAI script generation")
    chosen_model = (model or os.environ.get("OPENAI_SCRIPT_MODEL") or DEFAULT_MODEL).strip()
    # Script callers historically relied on the default story-package schema.
    if json_schema is None and use_json_schema is None:
        use_json_schema = True
    using_schema = json_schema is not None or use_json_schema is True
    spec = chat_request(
        prompt,
        model=chosen_model,
        json_schema=json_schema,
        schema_name=schema_name,
        system_content=system_content,
        use_json_schema=use_json_schema,
    )
    sender = transport or _urllib_transport
    try:
        raw = sender(spec, key)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        # Downgrade only when the API explicitly rejects structured-output schema.
        # Unrelated 400/404 (auth, quota, bad request) must not silently fall back.
        if using_schema and is_schema_compatibility_error(error.code, detail):
            return complete_chat(
                prompt,
                model=chosen_model,
                api_key=key,
                transport=transport,
                json_schema=None,
                schema_name=schema_name,
                system_content=system_content,
                use_json_schema=False,
            )
        raise GroundingError(f"OpenAI returned HTTP {error.code}: {redact(detail, key)}") from None
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GroundingError(f"OpenAI response was not JSON: {exc}") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GroundingError("OpenAI response did not include assistant content") from exc
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, Mapping) else str(part) for part in content
        )
    if not isinstance(content, str) or not content.strip():
        raise GroundingError("OpenAI assistant content was empty")
    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise GroundingError(f"OpenAI assistant content was not JSON: {exc}") from exc


def _urllib_transport(spec: dict[str, Any], api_key: str) -> bytes:
    body = json.dumps(spec["body"]).encode("utf-8")
    request = urllib.request.Request(
        spec["url"],
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method=spec["method"],
    )
    with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
        return response.read()
