"""Persian narration quality and engagement review for Reel scripts.

Runs after the story package is generated and before photograph retrieval or
ElevenLabs. Decisions are computed in Python from validated scores and glossary
checks; the model never gets a free pass via a lone ``approved`` flag.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.exceptions import GroundingError
from app.services.llm.openai_script import DEFAULT_MODEL, complete_chat
from app.services.llm.persian_script import (
    CHARS_PER_SECOND,
    Completer,
    claim_grounding_errors,
    finalize_model_story_package,
    script_prompt,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GLOSSARY_FILE = ROOT / "config" / "german_term_glossary.json"

_MODEL_USD_PER_MTOKEN = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}


def _estimate_tokens_from_text(text: str) -> int:
    """Rough token estimate without importing editorial_rank (avoids circular imports)."""

    return max(1, (len(text or "") + 3) // 4)

SCORE_KEYS = (
    "hook_strength",
    "listener_involvement",
    "curiosity_and_retention",
    "storytelling_flow",
    "natural_spoken_persian",
    "clarity",
    "practical_usefulness",
    "ending_quality",
)

NARRATION_REVIEW_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "approved",
        "overall_score",
        "scores",
        "score_evidence",
        "factual_errors",
        "editorial_issues",
        "weakest_sentence",
        "drop_off_risk",
        "rewrite_required",
        "reason",
    ],
    "properties": {
        "approved": {"type": "boolean"},
        "overall_score": {"type": "number"},
        "scores": {
            "type": "object",
            "additionalProperties": False,
            "required": list(SCORE_KEYS),
            "properties": {key: {"type": "number"} for key in SCORE_KEYS},
        },
        "score_evidence": {
            "type": "object",
            "additionalProperties": False,
            "required": list(SCORE_KEYS),
            "properties": {key: {"type": "string", "minLength": 1} for key in SCORE_KEYS},
        },
        "factual_errors": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scene", "claim", "problem"],
                "properties": {
                    "scene": {"type": "integer"},
                    "claim": {"type": "string"},
                    "problem": {"type": "string"},
                },
            },
        },
        "editorial_issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scene", "sentence", "problem", "severity", "suggested_improvement"],
                "properties": {
                    "scene": {"type": "integer"},
                    "sentence": {"type": "string"},
                    "problem": {"type": "string"},
                    "severity": {"type": "string"},
                    "suggested_improvement": {"type": "string"},
                },
            },
        },
        "weakest_sentence": {"type": "string"},
        "drop_off_risk": {
            "type": "object",
            "additionalProperties": False,
            "required": ["scene", "reason", "suggested_replacement"],
            "properties": {
                "scene": {"type": "integer"},
                "reason": {"type": "string"},
                "suggested_replacement": {"type": "string"},
            },
        },
        "rewrite_required": {"type": "boolean"},
        "reason": {"type": "string"},
    },
}

_REVIEW_SYSTEM = (
    "You are a Persian Instagram news narration editor for Iranians living in Germany. "
    "Reply with one JSON object only matching the narration review schema. "
    "Judge engagement, curiosity, spoken Persian, and storytelling. "
    "Never invent facts outside the fact pack. Every score needs concrete textual evidence."
)

CompleteFn = Callable[..., dict[str, Any]]


@dataclass
class NarrationReviewThresholds:
    min_overall: float = 80.0
    min_hook: float = 80.0
    min_curiosity: float = 75.0
    max_rewrites: int = 1
    min_spoken_seconds: float = 32.0
    target_spoken_seconds: float = 40.0


@dataclass
class NarrationReviewResult:
    approved: bool
    decision: str
    reason: str
    overall_score: float
    scores: dict[str, float] = field(default_factory=dict)
    score_evidence: dict[str, str] = field(default_factory=dict)
    factual_errors: list[dict[str, Any]] = field(default_factory=list)
    editorial_issues: list[dict[str, Any]] = field(default_factory=list)
    weakest_sentence: str = ""
    drop_off_risk: dict[str, Any] = field(default_factory=dict)
    rewrite_required: bool = False
    package: dict[str, Any] = field(default_factory=dict)
    original_package: dict[str, Any] = field(default_factory=dict)
    rewritten_package: dict[str, Any] | None = None
    reviews: list[dict[str, Any]] = field(default_factory=list)
    openai_calls: int = 0
    usd_est: float = 0.0
    spoken_seconds_est: float = 0.0

    def as_detail(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "decision": self.decision,
            "reason": self.reason,
            "overall_score": self.overall_score,
            "scores": dict(self.scores),
            "score_evidence": dict(self.score_evidence),
            "factual_errors": list(self.factual_errors),
            "editorial_issues": list(self.editorial_issues),
            "weakest_sentence": self.weakest_sentence,
            "drop_off_risk": dict(self.drop_off_risk),
            "rewrite_required": self.rewrite_required,
            "openai_calls": self.openai_calls,
            "usd_est": self.usd_est,
            "spoken_seconds_est": self.spoken_seconds_est,
            "reviews": list(self.reviews),
            "rewritten": self.rewritten_package is not None,
        }

    def cli_summary(self) -> str:
        lines = [
            "Narration Quality Review",
            "----------------------------------",
        ]
        labels = {
            "hook_strength": "Hook",
            "listener_involvement": "Listener involvement",
            "curiosity_and_retention": "Curiosity",
            "storytelling_flow": "Storytelling",
            "natural_spoken_persian": "Natural Persian",
            "clarity": "Clarity",
            "practical_usefulness": "Practical usefulness",
            "ending_quality": "Ending",
        }
        for key, label in labels.items():
            if key in self.scores:
                lines.append(f"{label + ':':<22} {int(round(self.scores[key]))}/100")
        lines.append(f"{'Overall:':<22} {int(round(self.overall_score))}/100")
        lines.append(f"{'Factual errors:':<22} {len(self.factual_errors)}")
        lines.append(f"{'Decision:':<22} {self.decision}")
        if self.reason:
            lines.append(f"Reason: {self.reason}")
        return "\n".join(lines)


def load_german_term_glossary(path: Path | None = None) -> dict[str, Any]:
    file_path = Path(path) if path is not None else DEFAULT_GLOSSARY_FILE
    if not file_path.is_file():
        return {}
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def estimate_spoken_seconds(package: Mapping[str, Any]) -> float:
    narration = " ".join(
        str(scene.get("narration") or "").strip()
        for scene in package.get("scenes") or []
        if isinstance(scene, Mapping)
    )
    if not narration:
        return 0.0
    return round(len(narration) / CHARS_PER_SECOND, 2)


def estimate_review_usage(prompt: str, *, model: str, expected_output_tokens: int = 900) -> dict[str, Any]:
    rates = _MODEL_USD_PER_MTOKEN.get(model) or _MODEL_USD_PER_MTOKEN["gpt-4o-mini"]
    input_tokens = _estimate_tokens_from_text(prompt)
    output_tokens = max(1, int(expected_output_tokens))
    usd = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    return {
        "model": model,
        "input_tokens_est": input_tokens,
        "output_tokens_est": output_tokens,
        "usd_est": round(usd, 6),
        "pricing_note": "estimate only; not a bill",
    }


def compute_overall_score(scores: Mapping[str, Any]) -> float:
    values = [float(scores[key]) for key in SCORE_KEYS if key in scores]
    if not values:
        return 0.0
    return round(sum(values) / len(values), 2)


def glossary_factual_errors(
    package: Mapping[str, Any],
    glossary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Reject known misleading Persian renderings of German policy terms."""

    errors: list[dict[str, Any]] = []
    scenes = package.get("scenes") or []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, Mapping):
            continue
        text = str(scene.get("narration") or "")
        for term, meta in glossary.items():
            if not isinstance(meta, Mapping):
                continue
            for bad in meta.get("misleading_fa") or []:
                if bad and bad in text:
                    preferred = ", ".join(str(item) for item in (meta.get("preferred_fa") or [])[:3])
                    errors.append(
                        {
                            "scene": index,
                            "claim": text.strip(),
                            "problem": (
                                f"misleading translation of {term}: found «{bad}»; "
                                f"prefer {preferred or term}"
                            ),
                        }
                    )
    return errors


def spoken_length_errors(
    package: Mapping[str, Any],
    *,
    min_spoken_seconds: float,
) -> list[str]:
    seconds = estimate_spoken_seconds(package)
    if seconds < float(min_spoken_seconds):
        return [
            f"spoken narration ~{seconds:.1f}s is below the {min_spoken_seconds:.0f}s minimum "
            f"(about {int(min_spoken_seconds * CHARS_PER_SECOND)} Persian characters needed)"
        ]
    return []


def build_review_prompt(
    *,
    fact_pack: Mapping[str, Any],
    editorial: Mapping[str, Any],
    package: Mapping[str, Any],
    audience_label: str,
    title: str,
    source_url: str,
    target_duration_seconds: float,
    glossary: Mapping[str, Any],
) -> str:
    scenes = [
        {
            "number": scene.get("number"),
            "narration": scene.get("narration"),
            "on_screen_text": scene.get("on_screen_text"),
            "duration_seconds": scene.get("duration_seconds"),
        }
        for scene in package.get("scenes") or []
        if isinstance(scene, Mapping)
    ]
    return (
        "Review this Persian Instagram Reel narration as ONE connected story for "
        f"listeners who are {audience_label}.\n"
        "Ask: if I were an Iranian living in Germany, would I want the next sentence?\n"
        "Score each dimension 0–100 and give concrete textual evidence for every score.\n"
        "Flag weak hooks, low curiosity, disconnected sentences, bureaucratic tone, "
        "repetition, abrupt endings, and misleading German-term translations.\n"
        "Do not invent facts. Do not approve unsupported claims.\n"
        f"Target spoken duration: ~{target_duration_seconds:.0f} seconds.\n"
        f"Original title: {title}\n"
        f"Source URL: {source_url}\n"
        f"GERMAN_TERM_GLOSSARY:\n{json.dumps(glossary, ensure_ascii=False)}\n"
        f"FACT_PACK:\n{json.dumps(fact_pack, ensure_ascii=False)}\n"
        f"EDITORIAL_REVIEW:\n{json.dumps(editorial, ensure_ascii=False)}\n"
        f"STORY_PACKAGE:\n{json.dumps({**dict(package), 'scenes': scenes}, ensure_ascii=False)}\n"
    )


def build_rewrite_prompt(
    *,
    fact_pack: Mapping[str, Any],
    editorial: Mapping[str, Any],
    package: Mapping[str, Any],
    review: Mapping[str, Any],
    title: str,
    source_url: str,
    target_duration_seconds: float,
    glossary: Mapping[str, Any],
) -> str:
    return (
        "Rewrite this Persian story_package once for stronger spoken engagement.\n"
        "Return ONLY one corrected story_package JSON object (pilot-1).\n"
        "Keep the same news event and only fact-pack-supported claims.\n"
        "Improve hook, listener involvement, curiosity, transitions, and ending takeaway.\n"
        "Use natural conversational Persian for Iranians in Germany.\n"
        "Use contextual attribution (مثل «طبق گزارش تگس‌شاو») when needed; "
        "avoid robotic «این خبر از … است».\n"
        f"Spoken length target: {target_duration_seconds:.0f}s "
        f"(about {int(target_duration_seconds * CHARS_PER_SECOND)} characters total).\n"
        "Update on_screen_text to match revised narration.\n"
        "Keep English photograph-search visual_prompt values.\n"
        f"Title: {title}\nSource: {source_url}\n"
        f"REVIEW_FEEDBACK:\n{json.dumps(review, ensure_ascii=False)}\n"
        f"GERMAN_TERM_GLOSSARY:\n{json.dumps(glossary, ensure_ascii=False)}\n"
        f"ORIGINAL_STORY_PACKAGE:\n{json.dumps(package, ensure_ascii=False)}\n"
        f"FACT_PACK:\n{json.dumps(fact_pack, ensure_ascii=False)}\n"
        f"EDITORIAL_REVIEW:\n{json.dumps(editorial, ensure_ascii=False)}\n"
        f"{script_prompt(fact_pack, editorial)}\n"
    )


def parse_review_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise GroundingError("narration review response must be a JSON object")
    scores_raw = payload.get("scores")
    if not isinstance(scores_raw, Mapping):
        raise GroundingError("narration review missing scores object")
    scores: dict[str, float] = {}
    for key in SCORE_KEYS:
        if key not in scores_raw:
            raise GroundingError(f"narration review missing score: {key}")
        try:
            value = float(scores_raw[key])
        except (TypeError, ValueError) as exc:
            raise GroundingError(f"narration review score invalid: {key}") from exc
        scores[key] = max(0.0, min(100.0, value))
    evidence_raw = payload.get("score_evidence")
    if not isinstance(evidence_raw, Mapping):
        raise GroundingError("narration review missing score_evidence")
    evidence: dict[str, str] = {}
    for key in SCORE_KEYS:
        text = str(evidence_raw.get(key) or "").strip()
        if len(text) < 8:
            raise GroundingError(f"narration review score_evidence too thin for {key}")
        evidence[key] = text
    factual = payload.get("factual_errors")
    if not isinstance(factual, list):
        raise GroundingError("narration review factual_errors must be a list")
    issues = payload.get("editorial_issues")
    if not isinstance(issues, list):
        raise GroundingError("narration review editorial_issues must be a list")
    drop = payload.get("drop_off_risk")
    if not isinstance(drop, Mapping):
        drop = {"scene": 0, "reason": "", "suggested_replacement": ""}
    overall = compute_overall_score(scores)
    return {
        "approved": bool(payload.get("approved")),
        "overall_score": overall,
        "scores": scores,
        "score_evidence": evidence,
        "factual_errors": [item for item in factual if isinstance(item, Mapping)],
        "editorial_issues": [item for item in issues if isinstance(item, Mapping)],
        "weakest_sentence": str(payload.get("weakest_sentence") or "").strip(),
        "drop_off_risk": {
            "scene": int(drop.get("scene") or 0),
            "reason": str(drop.get("reason") or "").strip(),
            "suggested_replacement": str(drop.get("suggested_replacement") or "").strip(),
        },
        "rewrite_required": bool(payload.get("rewrite_required")),
        "reason": str(payload.get("reason") or "").strip(),
        "model_approved": bool(payload.get("approved")),
    }


def decide_from_scores(
    review: Mapping[str, Any],
    *,
    thresholds: NarrationReviewThresholds,
    local_factual_errors: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Python gate. Never trust the model ``approved`` field alone."""

    factual = list(review.get("factual_errors") or [])
    for item in local_factual_errors or []:
        factual.append(dict(item))
    scores = dict(review.get("scores") or {})
    overall = compute_overall_score(scores)
    hook = float(scores.get("hook_strength") or 0)
    curiosity = float(scores.get("curiosity_and_retention") or 0)
    reasons: list[str] = []
    if factual:
        reasons.append(f"{len(factual)} factual error(s)")
    if overall < thresholds.min_overall:
        reasons.append(f"overall {overall:.0f} < {thresholds.min_overall:.0f}")
    if hook < thresholds.min_hook:
        reasons.append(f"hook {hook:.0f} < {thresholds.min_hook:.0f}")
    if curiosity < thresholds.min_curiosity:
        reasons.append(f"curiosity {curiosity:.0f} < {thresholds.min_curiosity:.0f}")
    approved = not reasons
    rewrite_required = (not approved) and not factual and (
        overall < thresholds.min_overall
        or hook < thresholds.min_hook
        or curiosity < thresholds.min_curiosity
    )
    # Factual errors never get a rewrite pass that invents fixes without grounding —
    # still allow one editorial rewrite attempt that must clear facts afterward.
    if factual and not approved:
        rewrite_required = True
    reason = "; ".join(reasons) if reasons else str(review.get("reason") or "meets thresholds")
    return {
        **dict(review),
        "overall_score": overall,
        "factual_errors": factual,
        "approved": approved,
        "rewrite_required": rewrite_required and not approved,
        "reason": reason,
        "decision": "APPROVED" if approved else "REWRITE_REQUIRED" if rewrite_required else "REJECTED",
    }


def _extract_content(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise GroundingError("narration review response must be a JSON object")
    if "scores" in payload:
        return payload
    if isinstance(payload.get("content"), Mapping):
        return payload["content"]
    return payload


def run_narration_review_once(
    *,
    fact_pack: Mapping[str, Any],
    editorial: Mapping[str, Any],
    package: Mapping[str, Any],
    title: str,
    source_url: str,
    audience_label: str = "Iranians living in Germany",
    thresholds: NarrationReviewThresholds | None = None,
    glossary: Mapping[str, Any] | None = None,
    model: str | None = None,
    complete: CompleteFn | None = None,
    api_key: str | None = None,
    transport=None,
) -> tuple[dict[str, Any], int, float]:
    """One review call. Returns (decision_dict, calls, usd_est)."""

    settings = thresholds or NarrationReviewThresholds()
    terms = dict(glossary) if glossary is not None else load_german_term_glossary()
    chosen_model = (model or os.environ.get("OPENAI_SCRIPT_MODEL") or DEFAULT_MODEL).strip()
    prompt = build_review_prompt(
        fact_pack=fact_pack,
        editorial=editorial,
        package=package,
        audience_label=audience_label,
        title=title,
        source_url=source_url,
        target_duration_seconds=settings.target_spoken_seconds,
        glossary=terms,
    )
    usage = estimate_review_usage(prompt, model=chosen_model)
    completer = complete or complete_chat
    kwargs: dict[str, Any] = {"model": chosen_model}
    if complete is None:
        kwargs.update(
            {
                "api_key": api_key,
                "transport": transport,
                "json_schema": NARRATION_REVIEW_JSON_SCHEMA,
                "schema_name": "narration_quality_review",
                "system_content": _REVIEW_SYSTEM,
                "use_json_schema": False,
            }
        )
    raw = completer(prompt, {"stage": "narration_review", "attempt": 1}, **kwargs)
    parsed = parse_review_payload(_extract_content(raw))
    local_facts = glossary_factual_errors(package, terms)
    grounding = claim_grounding_errors(package, fact_pack)
    for message in grounding:
        local_facts.append({"scene": 0, "claim": "", "problem": message})
    for message in spoken_length_errors(package, min_spoken_seconds=settings.min_spoken_seconds):
        local_facts.append({"scene": 0, "claim": "", "problem": message})
    decision = decide_from_scores(parsed, thresholds=settings, local_factual_errors=local_facts)
    return decision, 1, float(usage["usd_est"])


def rewrite_story_package_for_engagement(
    *,
    fact_pack: Mapping[str, Any],
    editorial: Mapping[str, Any],
    package: Mapping[str, Any],
    review: Mapping[str, Any],
    title: str,
    source_url: str,
    thresholds: NarrationReviewThresholds | None = None,
    glossary: Mapping[str, Any] | None = None,
    complete: Completer | None = None,
    model: str | None = None,
    api_key: str | None = None,
    transport=None,
) -> tuple[dict[str, Any], int, float]:
    """One engagement rewrite, then full structural/factual finalize."""

    settings = thresholds or NarrationReviewThresholds()
    terms = dict(glossary) if glossary is not None else load_german_term_glossary()
    chosen_model = (model or os.environ.get("OPENAI_SCRIPT_MODEL") or DEFAULT_MODEL).strip()
    prompt = build_rewrite_prompt(
        fact_pack=fact_pack,
        editorial=editorial,
        package=package,
        review=review,
        title=title,
        source_url=source_url,
        target_duration_seconds=settings.target_spoken_seconds,
        glossary=terms,
    )
    usage = estimate_review_usage(prompt, model=chosen_model, expected_output_tokens=1200)
    if complete is not None:
        raw = complete(
            prompt,
            {
                "stage": "narration_rewrite",
                "attempt": 1,
                "fact_pack": fact_pack,
                "editorial": editorial,
            },
        )
        package_out = finalize_model_story_package(
            raw,
            fact_pack,
            editorial,
            min_spoken_seconds=settings.min_spoken_seconds,
        )
        return package_out, 1, float(usage["usd_est"])

    raw = complete_chat(
        prompt,
        {"stage": "narration_rewrite", "fact_pack": fact_pack, "editorial": editorial},
        model=chosen_model,
        api_key=api_key,
        transport=transport,
        use_json_schema=True,
    )
    package_out = finalize_model_story_package(
        raw,
        fact_pack,
        editorial,
        min_spoken_seconds=settings.min_spoken_seconds,
    )
    return package_out, 1, float(usage["usd_est"])


def review_and_refine_story_package(
    *,
    fact_pack: Mapping[str, Any],
    editorial: Mapping[str, Any],
    package: Mapping[str, Any],
    title: str,
    source_url: str,
    audience_label: str = "Iranians living in Germany",
    thresholds: NarrationReviewThresholds | None = None,
    glossary_path: Path | None = None,
    model: str | None = None,
    review_complete: CompleteFn | None = None,
    rewrite_complete: Completer | None = None,
    api_key: str | None = None,
    transport=None,
    budget_usd: float | None = None,
) -> NarrationReviewResult:
    """Review once, optionally rewrite once, review again. Max two reviews."""

    settings = thresholds or NarrationReviewThresholds()
    glossary = load_german_term_glossary(glossary_path)
    original = dict(package)
    current = dict(package)
    reviews: list[dict[str, Any]] = []
    calls = 0
    usd = 0.0
    rewritten: dict[str, Any] | None = None

    # Pre-check spoken length / glossary before spending a review call when possible.
    pre_errors = glossary_factual_errors(current, glossary)
    for message in spoken_length_errors(current, min_spoken_seconds=settings.min_spoken_seconds):
        pre_errors.append({"scene": 0, "claim": "", "problem": message})

    first, c1, u1 = run_narration_review_once(
        fact_pack=fact_pack,
        editorial=editorial,
        package=current,
        title=title,
        source_url=source_url,
        audience_label=audience_label,
        thresholds=settings,
        glossary=glossary,
        model=model,
        complete=review_complete,
        api_key=api_key,
        transport=transport,
    )
    # Merge pre-check length issues if the model missed them.
    if pre_errors:
        first = decide_from_scores(first, thresholds=settings, local_factual_errors=pre_errors)
    calls += c1
    usd += u1
    if budget_usd is not None and usd > budget_usd:
        raise GroundingError(f"narration review estimate ${usd:.4f} exceeds remaining budget ${budget_usd:.4f}")
    reviews.append({"pass": 1, **first})

    if first["approved"]:
        return NarrationReviewResult(
            approved=True,
            decision="APPROVED",
            reason=first["reason"],
            overall_score=float(first["overall_score"]),
            scores=dict(first["scores"]),
            score_evidence=dict(first.get("score_evidence") or {}),
            factual_errors=list(first.get("factual_errors") or []),
            editorial_issues=list(first.get("editorial_issues") or []),
            weakest_sentence=str(first.get("weakest_sentence") or ""),
            drop_off_risk=dict(first.get("drop_off_risk") or {}),
            rewrite_required=False,
            package=current,
            original_package=original,
            rewritten_package=None,
            reviews=reviews,
            openai_calls=calls,
            usd_est=round(usd, 6),
            spoken_seconds_est=estimate_spoken_seconds(current),
        )

    if settings.max_rewrites < 1 or not first.get("rewrite_required", True):
        return NarrationReviewResult(
            approved=False,
            decision="REJECTED",
            reason=first["reason"],
            overall_score=float(first["overall_score"]),
            scores=dict(first["scores"]),
            score_evidence=dict(first.get("score_evidence") or {}),
            factual_errors=list(first.get("factual_errors") or []),
            editorial_issues=list(first.get("editorial_issues") or []),
            weakest_sentence=str(first.get("weakest_sentence") or ""),
            drop_off_risk=dict(first.get("drop_off_risk") or {}),
            rewrite_required=False,
            package=current,
            original_package=original,
            rewritten_package=None,
            reviews=reviews,
            openai_calls=calls,
            usd_est=round(usd, 6),
            spoken_seconds_est=estimate_spoken_seconds(current),
        )

    rewritten, c2, u2 = rewrite_story_package_for_engagement(
        fact_pack=fact_pack,
        editorial=editorial,
        package=current,
        review=first,
        title=title,
        source_url=source_url,
        thresholds=settings,
        glossary=glossary,
        complete=rewrite_complete,
        model=model,
        api_key=api_key,
        transport=transport,
    )
    calls += c2
    usd += u2
    if budget_usd is not None and usd > budget_usd:
        raise GroundingError(f"narration rewrite estimate ${usd:.4f} exceeds remaining budget ${budget_usd:.4f}")
    current = rewritten

    second, c3, u3 = run_narration_review_once(
        fact_pack=fact_pack,
        editorial=editorial,
        package=current,
        title=title,
        source_url=source_url,
        audience_label=audience_label,
        thresholds=settings,
        glossary=glossary,
        model=model,
        complete=review_complete,
        api_key=api_key,
        transport=transport,
    )
    calls += c3
    usd += u3
    reviews.append({"pass": 2, **second})

    approved = bool(second["approved"])
    return NarrationReviewResult(
        approved=approved,
        decision="APPROVED" if approved else "REJECTED",
        reason=second["reason"],
        overall_score=float(second["overall_score"]),
        scores=dict(second["scores"]),
        score_evidence=dict(second.get("score_evidence") or {}),
        factual_errors=list(second.get("factual_errors") or []),
        editorial_issues=list(second.get("editorial_issues") or []),
        weakest_sentence=str(second.get("weakest_sentence") or ""),
        drop_off_risk=dict(second.get("drop_off_risk") or {}),
        rewrite_required=False,
        package=current,
        original_package=original,
        rewritten_package=rewritten,
        reviews=reviews,
        openai_calls=calls,
        usd_est=round(usd, 6),
        spoken_seconds_est=estimate_spoken_seconds(current),
    )


def write_narration_review_artifacts(result: NarrationReviewResult, destination: Path) -> Path:
    """Persist review JSON next to the story package."""

    path = destination if destination.suffix == ".json" else destination / "narration_review.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **result.as_detail(),
        "original_story_package": result.original_package,
        "final_story_package": result.package,
        "rewritten_story_package": result.rewritten_package,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
