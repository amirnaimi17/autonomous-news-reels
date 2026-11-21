"""Grounded Persian Reel scripts from fact packs and editorial briefs.

This module turns the pilot contracts (``fact_pack.json``, ``editorial_review.json``,
``story_package.json``) into the dict the Reel pipeline expects. It never calls a
network API by itself; callers inject a completer or use ``openai_script``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.core.exceptions import GroundingError
from app.services.grounding import numbers_missing_from_source
from app.services.news.audience import audience_filter
from app.services.text import plain_text

# Measured from the approved Aran sample: 216 characters in 18.08 seconds.
CHARS_PER_SECOND = 216 / 18.08
# Catalog ElevenLabs eleven_v4 Persian rate used only for an estimate, not a bill.
ELEVENLABS_USD_PER_CHAR = 0.08 / 1000

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_PERSIAN = re.compile(r"[\u0600-\u06FF]")

Completer = Callable[[str, Mapping[str, Any]], Mapping[str, Any] | str]


def build_fact_pack(
    *,
    title: str,
    summary: str,
    url: str,
    publisher: str,
    published_at: datetime | None,
    excerpt: str = "",
    event_id: str | None = None,
    retrieved_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the pilot fact-pack shape from a verified candidate."""

    clean_title = plain_text(title)
    clean_summary = plain_text(summary)
    clean_excerpt = plain_text(excerpt)
    stamp = (retrieved_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    published = None
    if published_at is not None:
        published = published_at.astimezone(timezone.utc).isoformat()
    source = {"publisher": publisher.strip() or "unknown", "url": url, "published_at": published}
    facts: list[dict[str, Any]] = []
    if clean_title:
        facts.append({"text": clean_title, "source_urls": [url]})
    for sentence in _sentences(clean_summary):
        facts.append({"text": sentence, "source_urls": [url]})
    if clean_excerpt:
        for sentence in _sentences(clean_excerpt)[:4]:
            if sentence not in {item["text"] for item in facts}:
                facts.append({"text": sentence, "source_urls": [url]})
    if not facts:
        facts.append({"text": clean_title or url, "source_urls": [url]})
    return {
        "event_id": event_id or _event_id(url, clean_title),
        "status": "READY",
        "retrieved_at": stamp.isoformat(),
        "event_summary": clean_summary or clean_title,
        "sources": [source],
        "verified_facts": facts,
        "uncertainties": [],
        "duplicate_risk": "none known",
    }


def build_editorial_brief(
    fact_pack: Mapping[str, Any],
    *,
    title: str,
    summary: str,
    audience: str = "Iranians living in Germany",
) -> dict[str, Any]:
    """Build the pilot editorial-review shape for an approved story."""

    urls = [item["url"] for item in fact_pack.get("sources") or [] if isinstance(item, Mapping) and item.get("url")]
    text = f"{title}\n{summary}"
    filter_result = audience_filter(text)
    return {
        "event_id": fact_pack["event_id"],
        "decision": "APPROVE",
        "rationale": (
            f"The verified source supports a Reel for {audience}. "
            f"Audience filter: {filter_result.result}."
        ),
        "limitations": [
            "Use only facts present in the fact pack.",
            "Attribute claims to the listed publishers.",
            "Do not invent outcomes, trends, or figures.",
        ],
        "audience_relevance": {
            "affected_audience": audience,
            "practical_relevance": plain_text(summary) or plain_text(title),
            "evidence_urls": urls,
            "publication_reason": f"The story matches a household topic: {plain_text(title)}",
        },
    }


_STORY_PACKAGE_SCHEMA_TEXT = """
Required top-level JSON object (schema_version pilot-1):
{
  "schema_version": "pilot-1",
  "event_id": "<same as fact pack>",
  "language": "fa-IR",
  "audience": "Iranians living in Germany",
  "headline": "<Persian headline>",
  "source_urls": ["https://..."],
  "claims": [{"text": "...", "source_urls": ["https://..."]}],
  "duration_seconds": 40,
  "duration_policy": "completeness",
  "scenes": [
    {
      "number": 1,
      "duration_seconds": 9,
      "narration": "<Persian spoken line with attribution>",
      "on_screen_text": "<short Persian caption>",
      "visual_prompt": "<English photograph search description>"
    }
  ],
  "disclaimers": []
}

CRITICAL:
- "scenes" MUST be a JSON array/list of 3–8 objects. Never an object/map keyed by numbers.
- Do not nest scenes under another key.
- visual_prompt must describe a real-world photograph useful for stock/Commons search
  (places, objects, documents, buildings). Do NOT use generic graphic/typography cards.
- Do not invent numbers, dates, outcomes, or quotes outside the fact pack.
""".strip()


def script_prompt(fact_pack: Mapping[str, Any], editorial: Mapping[str, Any]) -> str:
    """Prompt for a model that must return a pilot ``story_package`` JSON object."""

    return (
        "You write Instagram Reel narration for Persian-speaking people living in Germany.\n"
        "Return ONLY one JSON object. No markdown fences.\n"
        f"{_STORY_PACKAGE_SCHEMA_TEXT}\n"
        "Rules:\n"
        "- language must be fa-IR.\n"
        "- Write natural spoken Persian in short complete sentences.\n"
        "- Put attribution in the same sentence as each claim.\n"
        "- Aim for 35–45 seconds total; set duration_policy to completeness when needed.\n"
        "- Every material claim needs claims[].source_urls from the fact pack.\n"
        "- Digits may stay in narration.\n"
        f"FACT_PACK:\n{json.dumps(fact_pack, ensure_ascii=False)}\n"
        f"EDITORIAL_REVIEW:\n{json.dumps(editorial, ensure_ascii=False)}\n"
    )


def correction_prompt(
    fact_pack: Mapping[str, Any],
    editorial: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | str,
    errors: list[str],
) -> str:
    """Ask the model to fix an invalid package. Never invent scenes locally."""

    return (
        "Your previous story_package JSON failed validation.\n"
        "Return ONLY a corrected JSON object that fully matches the schema.\n"
        "Do not invent new facts. Keep Persian narration grounded in the fact pack.\n"
        "Ensure top-level scenes is a JSON array of 3–8 scene objects.\n"
        "Ensure each visual_prompt is an English photograph search description.\n"
        f"VALIDATION_ERRORS:\n{json.dumps(errors, ensure_ascii=False)}\n"
        f"PREVIOUS_RESPONSE:\n{json.dumps(previous, ensure_ascii=False) if isinstance(previous, Mapping) else previous}\n"
        f"{_STORY_PACKAGE_SCHEMA_TEXT}\n"
        f"FACT_PACK:\n{json.dumps(fact_pack, ensure_ascii=False)}\n"
        f"EDITORIAL_REVIEW:\n{json.dumps(editorial, ensure_ascii=False)}\n"
    )


_GRAPHIC_VISUAL_HINTS = (
    "typographic",
    "typography",
    "title card",
    "type card",
    "graphic card",
    "amount card",
    "status card",
    "attribution card",
    "solid color",
    "no photograph",
    "text only",
    "closing card",
    "opener card",
)


def structure_errors(raw: Mapping[str, Any]) -> list[str]:
    """Immediate structural checks before normalization / pilot validator."""

    errors: list[str] = []
    scenes = raw.get("scenes")
    if scenes is None:
        errors.append("story package scenes is missing")
    elif isinstance(scenes, dict):
        errors.append("story package scenes must be a list, not an object/map")
    elif not isinstance(scenes, list):
        errors.append("story package scenes must be a list")
    elif not 3 <= len(scenes) <= 8:
        errors.append(f"scenes must contain 3–8 items, got {len(scenes)}")
    else:
        for index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, Mapping):
                errors.append(f"scene {index} must be an object")
                continue
            if not str(scene.get("narration") or "").strip():
                errors.append(f"scene {index} needs narration")
            visual = str(scene.get("visual_prompt") or "").strip()
            if not visual:
                errors.append(f"scene {index} needs visual_prompt")
            elif not re.search(r"[A-Za-z]{3,}", visual):
                errors.append(f"scene {index} visual_prompt must be English photograph search text")
            elif any(hint in visual.casefold() for hint in _GRAPHIC_VISUAL_HINTS):
                errors.append(
                    f"scene {index} visual_prompt looks like a graphic placeholder; "
                    "use a real photograph search description"
                )
    return errors


def parse_model_story_package(payload: Mapping[str, Any] | str) -> dict[str, Any]:
    """Parse a model response into a story package dict."""

    if isinstance(payload, Mapping):
        data = dict(payload)
    else:
        text = payload.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
    if not isinstance(data, dict):
        raise GroundingError("model response was not a JSON object")
    return data


def normalize_story_package(
    raw: Mapping[str, Any],
    fact_pack: Mapping[str, Any],
    editorial: Mapping[str, Any],
) -> dict[str, Any]:
    """Fill required pilot fields and estimate missing scene durations."""

    package = dict(raw)
    package["schema_version"] = "pilot-1"
    package["event_id"] = str(fact_pack.get("event_id") or package.get("event_id") or "")
    package["language"] = package.get("language") or "fa-IR"
    audience = (
        ((editorial.get("audience_relevance") or {}) if isinstance(editorial.get("audience_relevance"), Mapping) else {}).get(
            "affected_audience"
        )
        or package.get("audience")
        or "Iranians living in Germany"
    )
    package["audience"] = str(audience)
    if not str(package.get("headline") or "").strip():
        package["headline"] = str(fact_pack.get("event_summary") or package["event_id"])
    source_urls = list(package.get("source_urls") or [])
    if not source_urls:
        source_urls = [
            item["url"]
            for item in fact_pack.get("sources") or []
            if isinstance(item, Mapping) and isinstance(item.get("url"), str)
        ]
    package["source_urls"] = source_urls
    if not isinstance(package.get("claims"), list) or not package["claims"]:
        package["claims"] = [
            {"text": item["text"], "source_urls": list(item.get("source_urls") or source_urls[:1])}
            for item in fact_pack.get("verified_facts") or []
            if isinstance(item, Mapping) and item.get("text")
        ]
    if not isinstance(package.get("disclaimers"), list):
        package["disclaimers"] = []
    early = structure_errors(package)
    if early:
        raise GroundingError("; ".join(early))
    scenes = package.get("scenes")
    if not isinstance(scenes, list):
        raise GroundingError("story package scenes must be a list")
    normalized_scenes: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, Mapping):
            raise GroundingError(f"scene {index} must be an object")
        item = dict(scene)
        item["number"] = index
        narration = str(item.get("narration") or "").strip()
        if not narration:
            raise GroundingError(f"scene {index} needs narration")
        item["narration"] = narration
        item["on_screen_text"] = str(item.get("on_screen_text") or "").strip() or _short_caption(narration)
        visual = str(item.get("visual_prompt") or "").strip()
        if not visual:
            raise GroundingError(f"scene {index} needs visual_prompt for photograph search")
        item["visual_prompt"] = visual
        seconds = item.get("duration_seconds")
        if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or seconds <= 0:
            item["duration_seconds"] = round(max(len(narration) / CHARS_PER_SECOND, 3.0), 2)
        else:
            item["duration_seconds"] = float(seconds)
        normalized_scenes.append(item)
    package["scenes"] = normalized_scenes
    total = round(sum(float(scene["duration_seconds"]) for scene in normalized_scenes), 2)
    package["duration_seconds"] = total
    if total < 35 or total > 45:
        package["duration_policy"] = package.get("duration_policy") or "completeness"
    return package


def validate_story_package_structure(package: Mapping[str, Any], *, allow_demo: bool = False) -> list[str]:
    """Run the pilot structural validator without inventing a second schema."""

    path = (
        Path(__file__).resolve().parents[3]
        / ".cursor"
        / "skills"
        / "verify-reel-pilot"
        / "scripts"
        / "validate_story_package.py"
    )
    spec = importlib.util.spec_from_file_location("validate_story_package_runtime", path)
    if spec is None or spec.loader is None:
        return ["story package validator is missing"]
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.validate(dict(package), allow_demo=allow_demo))


def claim_grounding_errors(package: Mapping[str, Any], fact_pack: Mapping[str, Any]) -> list[str]:
    """Return factual grounding failures against the approved fact pack."""

    errors: list[str] = []
    allowed = {
        item["url"]
        for item in fact_pack.get("sources") or []
        if isinstance(item, Mapping) and isinstance(item.get("url"), str)
    }
    for url in package.get("source_urls") or []:
        if url not in allowed:
            errors.append(f"source_urls includes URL absent from the fact pack: {url}")
    source_text = _fact_pack_text(fact_pack)
    claims = package.get("claims")
    if not isinstance(claims, list) or not claims:
        errors.append("claims must be present for factual review")
        return errors
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, Mapping):
            errors.append(f"claim {index} must be an object")
            continue
        text = str(claim.get("text") or "").strip()
        if not text:
            errors.append(f"claim {index} needs text")
            continue
        urls = claim.get("source_urls")
        if not isinstance(urls, list) or not urls:
            errors.append(f"claim {index} needs source_urls")
        else:
            for url in urls:
                if url not in allowed:
                    errors.append(f"claim {index} cites a URL absent from the fact pack")
                    break
        missing = numbers_missing_from_source(text, source_text)
        if missing:
            errors.append(f"claim {index} introduces figures not in the fact pack: {', '.join(missing)}")
    narration = " ".join(
        str(scene.get("narration") or "")
        for scene in package.get("scenes") or []
        if isinstance(scene, Mapping)
    )
    missing_narration = numbers_missing_from_source(narration, source_text)
    if missing_narration:
        errors.append(f"narration introduces figures not in the fact pack: {', '.join(missing_narration)}")
    if str(package.get("language") or "").startswith("fa") and not _PERSIAN.search(narration):
        errors.append("fa-IR narration must contain Persian script")
    return errors


def _finalize_package(
    raw: Mapping[str, Any] | str,
    fact_pack: Mapping[str, Any],
    editorial: Mapping[str, Any],
) -> dict[str, Any]:
    parsed = parse_model_story_package(raw)
    early = structure_errors(parsed)
    if early:
        raise GroundingError("; ".join(early))
    package = normalize_story_package(parsed, fact_pack, editorial)
    structural = validate_story_package_structure(package)
    if structural:
        raise GroundingError("; ".join(structural))
    grounding = claim_grounding_errors(package, fact_pack)
    if grounding:
        raise GroundingError("; ".join(grounding))
    return package


def generate_persian_story_package(
    fact_pack: Mapping[str, Any],
    editorial: Mapping[str, Any],
    *,
    complete: Completer,
) -> dict[str, Any]:
    """Ask the completer for a story package and ground-check the result.

    On invalid structure, performs at most one correction call with the
    validation errors. Never invents missing narration scenes locally.
    """

    if fact_pack.get("status") != "READY":
        raise GroundingError("fact pack is not READY")
    if editorial.get("decision") != "APPROVE":
        raise GroundingError("editorial decision is not APPROVE")

    calls = 0
    prompt = script_prompt(fact_pack, editorial)
    raw = complete(prompt, {"fact_pack": fact_pack, "editorial": editorial, "attempt": 1})
    calls += 1
    try:
        package = _finalize_package(raw, fact_pack, editorial)
        package["_openai_script_calls"] = calls
        return package
    except GroundingError as first_error:
        errors = [part.strip() for part in str(first_error).split(";") if part.strip()]
        retry_prompt = correction_prompt(
            fact_pack,
            editorial,
            previous=raw if isinstance(raw, Mapping) else str(raw),
            errors=errors or [str(first_error)],
        )
        corrected = complete(
            retry_prompt,
            {
                "fact_pack": fact_pack,
                "editorial": editorial,
                "attempt": 2,
                "correction": True,
                "previous_errors": errors,
            },
        )
        calls += 1
        try:
            package = _finalize_package(corrected, fact_pack, editorial)
        except GroundingError as second_error:
            raise GroundingError(
                f"story package invalid after correction attempt: {second_error} "
                f"(openai_script_calls={calls})"
            ) from second_error
        package["_openai_script_calls"] = calls
        return package


def _public_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """Drop internal bookkeeping keys before persistence or pipeline handoff."""

    return {key: value for key, value in package.items() if not str(key).startswith("_")}


def pipeline_script_from_package(package: Mapping[str, Any]) -> dict[str, Any]:
    """Map a grounded story package onto the Reel pipeline script dict."""

    public = _public_package(package)
    scenes = [scene for scene in public.get("scenes") or [] if isinstance(scene, Mapping)]
    narration = " ".join(str(scene.get("narration") or "").strip() for scene in scenes)
    caption = str(scenes[0].get("on_screen_text") if scenes else public.get("headline") or "").strip()
    characters = len(narration)
    return {
        "status": "ready",
        "narration": narration,
        "caption": caption,
        "angle": str(public.get("headline") or ""),
        "storyboard_json": json.dumps(
            [
                {
                    "number": scene.get("number"),
                    "duration_seconds": scene.get("duration_seconds"),
                    "narration": scene.get("narration"),
                    "on_screen_text": scene.get("on_screen_text"),
                    "visual_prompt": scene.get("visual_prompt"),
                }
                for scene in scenes
            ],
            ensure_ascii=False,
        ),
        "voice_estimate_usd": round(characters * ELEVENLABS_USD_PER_CHAR, 6),
        "story_package": public,
        "provider": "persian_grounded",
        "openai_script_calls": int(package.get("_openai_script_calls") or 1),
    }


def write_story_package(package: Mapping[str, Any], destination: Path) -> Path:
    """Persist ``story_package.json`` next to other generated Reel artifacts."""

    path = destination if destination.suffix == ".json" else destination / "story_package.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_public_package(package), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _event_id(url: str, title: str) -> str:
    digest = hashlib.sha256(f"{url}\n{title}".encode("utf-8")).hexdigest()[:12]
    host = urlsplit(url).netloc.replace(".", "-") or "event"
    return f"{host}-{digest}"


def _sentences(text: str) -> list[str]:
    if not text:
        return []
    return [part.strip() for part in _SENTENCE.split(text) if part.strip()]


def _fact_pack_text(fact_pack: Mapping[str, Any]) -> str:
    parts = [str(fact_pack.get("event_summary") or "")]
    for item in fact_pack.get("verified_facts") or []:
        if isinstance(item, Mapping):
            parts.append(str(item.get("text") or ""))
    for item in fact_pack.get("sources") or []:
        if isinstance(item, Mapping):
            parts.append(str(item.get("publisher") or ""))
            parts.append(str(item.get("published_at") or ""))
    return "\n".join(parts)


def _short_caption(narration: str) -> str:
    cleaned = " ".join(narration.split())
    if len(cleaned) <= 48:
        return cleaned
    trimmed = cleaned[:47].rsplit(" ", 1)[0]
    return trimmed or cleaned[:47]
