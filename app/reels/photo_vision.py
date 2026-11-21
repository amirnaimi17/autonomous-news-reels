"""Batched vision relevance checks for Reel scene photographs.

Metadata keyword hits are not enough. After a shortlist is downloaded, a single
multimodal OpenAI request scores every candidate against the scene brief.
Thumbnails are used to keep cost low. Inject ``complete`` in tests.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.exceptions import ConfigurationError, GroundingError
from app.services.llm.openai_script import DEFAULT_MODEL, ENV_NAME, api_key_from_env

API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_VISION_MODEL = os.getenv("REEL_PHOTO_VISION_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
MIN_VISUAL_RELEVANCE = 80
DEFAULT_SHORTLIST = 4
THUMB_MAX_EDGE = 512

VisionCompleter = Callable[[dict[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class VisionCandidateInput:
    candidate_id: str
    path: Path
    title: str = ""
    source_url: str = ""


@dataclass(frozen=True)
class VisionScore:
    candidate_id: str
    relevance: int
    misleading: bool
    unrelated_flags: bool
    suitable_vertical: bool
    reason: str = ""

    @property
    def accepted(self) -> bool:
        return (
            self.relevance >= MIN_VISUAL_RELEVANCE
            and not self.misleading
            and not self.unrelated_flags
            and self.suitable_vertical
        )


VISION_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "id",
                    "relevance",
                    "misleading",
                    "unrelated_flags",
                    "suitable_vertical",
                    "reason",
                ],
                "properties": {
                    "id": {"type": "string"},
                    "relevance": {"type": "integer"},
                    "misleading": {"type": "boolean"},
                    "unrelated_flags": {"type": "boolean"},
                    "suitable_vertical": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}


_SYSTEM = (
    "You score news-reel photograph candidates. Reply with one JSON object only. "
    "relevance is 0-100 for how well the IMAGE CONTENT matches the scene brief and story topic. "
    "Mark misleading=true when the photo would mislead viewers about the news. "
    "Mark unrelated_flags=true when the image shows national flags or political symbols "
    "that do not belong to the story topic (for example Israeli flags for a UK-EU story). "
    "suitable_vertical=false for unusable crops, pure text plates, or extreme panoramas. "
    "Do not reward metadata keywords; judge only what is visible."
)


def encode_thumbnail_jpeg(path: Path, *, max_edge: int = THUMB_MAX_EDGE) -> bytes:
    """Return a small JPEG thumbnail for vision scoring (ffmpeg; no PIL required)."""

    if not path.is_file():
        raise GroundingError(f"vision thumbnail source missing: {path}")
    with tempfile.TemporaryDirectory(prefix="reel-vision-") as tmp:
        out = Path(tmp) / "thumb.jpg"
        scale = f"scale='min({int(max_edge)},iw)':-2"
        completed = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(path),
                "-vf",
                scale,
                "-frames:v",
                "1",
                "-q:v",
                "6",
                str(out),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not out.is_file():
            raise GroundingError(f"ffmpeg thumbnail failed for {path}: {completed.stderr[-400:]}")
        data = out.read_bytes()
        if len(data) < 500:
            raise GroundingError(f"vision thumbnail too small for {path}")
        return data


def _data_url(jpeg_bytes: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")


def build_vision_request(
    *,
    story_topic: str,
    scene_number: int,
    scene_brief: str,
    candidates: Sequence[VisionCandidateInput],
    thumbnails: Mapping[str, bytes],
    model: str = DEFAULT_VISION_MODEL,
) -> dict[str, Any]:
    """Build a Chat Completions multimodal request for one scene shortlist."""

    if not candidates:
        raise GroundingError("vision shortlist is empty")
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"STORY_TOPIC: {story_topic.strip()}\n"
                f"SCENE_NUMBER: {scene_number}\n"
                f"SCENE_BRIEF: {scene_brief.strip()}\n"
                "Score every candidate image below. Return JSON with key candidates.\n"
            ),
        }
    ]
    for item in candidates:
        thumb = thumbnails.get(item.candidate_id)
        if not thumb:
            raise GroundingError(f"missing thumbnail for candidate {item.candidate_id}")
        user_content.append(
            {
                "type": "text",
                "text": (
                    f"CANDIDATE_ID={item.candidate_id}\n"
                    f"TITLE={item.title}\n"
                    f"SOURCE={item.source_url}\n"
                ),
            }
        )
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": _data_url(thumb), "detail": "low"},
            }
        )
    return {
        "method": "POST",
        "url": API_URL,
        "body": {
            "model": model,
            "temperature": 0.0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "reel_photo_vision_scores",
                    "strict": True,
                    "schema": VISION_RESULT_SCHEMA,
                },
            },
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_content},
            ],
        },
    }


def parse_vision_response(payload: Mapping[str, Any], *, expected_ids: Sequence[str]) -> list[VisionScore]:
    """Parse model JSON into VisionScore rows; missing ids fail closed as rejected."""

    rows = payload.get("candidates")
    if not isinstance(rows, list) or not rows:
        raise GroundingError("vision response missing candidates")
    by_id: dict[str, VisionScore] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        relevance = int(row.get("relevance") or 0)
        relevance = max(0, min(100, relevance))
        by_id[cid] = VisionScore(
            candidate_id=cid,
            relevance=relevance,
            misleading=bool(row.get("misleading")),
            unrelated_flags=bool(row.get("unrelated_flags")),
            suitable_vertical=bool(row.get("suitable_vertical")),
            reason=str(row.get("reason") or "").strip(),
        )
    ordered: list[VisionScore] = []
    for cid in expected_ids:
        score = by_id.get(cid)
        if score is None:
            ordered.append(
                VisionScore(
                    candidate_id=cid,
                    relevance=0,
                    misleading=True,
                    unrelated_flags=False,
                    suitable_vertical=False,
                    reason="missing from vision response",
                )
            )
        else:
            ordered.append(score)
    return ordered


def _default_vision_transport(spec: dict[str, Any], api_key: str) -> bytes:
    import urllib.request

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
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        return response.read()


def _parse_assistant_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise GroundingError(f"vision API response was not JSON: {exc}") from exc
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise GroundingError("vision API response missing assistant content") from exc
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") if isinstance(part, Mapping) else str(part) for part in content
        )
    if not isinstance(content, str) or not content.strip():
        raise GroundingError("vision assistant content was empty")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise GroundingError(f"vision assistant content was not JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GroundingError("vision assistant JSON must be an object")
    return parsed


def evaluate_scene_candidates(
    *,
    story_topic: str,
    scene_number: int,
    scene_brief: str,
    candidates: Sequence[VisionCandidateInput],
    model: str | None = None,
    api_key: str | None = None,
    complete: VisionCompleter | None = None,
    transport=None,
) -> list[VisionScore]:
    """Score a shortlist of downloaded photos for one scene in a single batched call."""

    if not candidates:
        return []
    thumbs: dict[str, bytes] = {}
    for item in candidates:
        thumbs[item.candidate_id] = encode_thumbnail_jpeg(item.path)
    if complete is not None:
        # Tests inject a fake scorer that receives a plain context dict.
        payload = complete(
            {
                "story_topic": story_topic,
                "scene_number": scene_number,
                "scene_brief": scene_brief,
                "candidates": [
                    {
                        "id": item.candidate_id,
                        "title": item.title,
                        "source_url": item.source_url,
                        "path": str(item.path),
                    }
                    for item in candidates
                ],
            }
        )
        if not isinstance(payload, Mapping):
            raise GroundingError("vision completer must return a mapping")
        return parse_vision_response(payload, expected_ids=[item.candidate_id for item in candidates])

    key = (api_key if api_key is not None else api_key_from_env()).strip()
    if not key:
        raise ConfigurationError(f"{ENV_NAME} is required for photograph vision scoring")
    chosen = (model or DEFAULT_VISION_MODEL).strip() or DEFAULT_VISION_MODEL
    spec = build_vision_request(
        story_topic=story_topic,
        scene_number=scene_number,
        scene_brief=scene_brief,
        candidates=candidates,
        thumbnails=thumbs,
        model=chosen,
    )
    sender = transport or _default_vision_transport
    raw = sender(spec, key)
    parsed = _parse_assistant_json(raw)
    return parse_vision_response(parsed, expected_ids=[item.candidate_id for item in candidates])


def pick_best_accepted(scores: Sequence[VisionScore]) -> VisionScore | None:
    """Return the highest-scoring accepted candidate, if any."""

    accepted = [item for item in scores if item.accepted]
    if not accepted:
        return None
    return max(accepted, key=lambda item: item.relevance)


def estimate_vision_usd(*, scenes: int, shortlist: int = DEFAULT_SHORTLIST, model: str = DEFAULT_VISION_MODEL) -> float:
    """Rough upper-bound estimate for batched vision calls (not a bill)."""

    # gpt-4o-mini vision is cheap; keep a conservative per-scene budget for gates.
    del model
    per_scene = 0.01 + 0.002 * max(1, shortlist)
    return round(per_scene * max(0, scenes), 4)
