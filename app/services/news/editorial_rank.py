"""AI-assisted editorial ranking over already-retrieved news candidates.

The model may only choose among supplied article IDs. It never invents URLs.
Live OpenAI calls stay behind an injectable transport and an approval flag.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.core.exceptions import ConfigurationError, GroundingError
from app.services.llm.openai_script import DEFAULT_MODEL, complete_chat

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUDIENCES_FILE = ROOT / "config" / "editorial_audiences.json"

# Approximate public Chat Completions prices for cost reporting only.
_MODEL_USD_PER_MTOKEN = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
}

CompleteFn = Callable[..., dict[str, Any]]


def estimate_tokens_from_text(text: str) -> int:
    """Rough token estimate without a tokenizer dependency (~4 chars/token)."""

    return max(1, (len(text or "") + 3) // 4)


def estimate_ranking_usage(prompt: str, *, model: str, expected_output_tokens: int = 700) -> dict[str, Any]:
    """Estimate OpenAI ranking cost before a live call is approved."""

    rates = _MODEL_USD_PER_MTOKEN.get(model) or _MODEL_USD_PER_MTOKEN["gpt-4o-mini"]
    input_tokens = estimate_tokens_from_text(prompt)
    output_tokens = max(1, int(expected_output_tokens))
    usd = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    return {
        "model": model,
        "input_tokens_est": input_tokens,
        "output_tokens_est": output_tokens,
        "usd_est": round(usd, 6),
        "pricing_note": "estimate only; not a bill",
    }


def usage_from_openai_payload(payload: Mapping[str, Any], *, model: str) -> dict[str, Any]:
    """Prefer API usage when present; otherwise return an empty usage object."""

    usage = payload.get("usage") if isinstance(payload, Mapping) else None
    if not isinstance(usage, Mapping):
        return {"model": model, "input_tokens": None, "output_tokens": None, "usd_est": None}
    input_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    rates = _MODEL_USD_PER_MTOKEN.get(model) or _MODEL_USD_PER_MTOKEN["gpt-4o-mini"]
    usd = (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
    return {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "usd_est": round(usd, 6),
        "pricing_note": "derived from API usage fields when present",
    }


@dataclass(frozen=True)
class AudienceProfile:
    id: str
    label: str
    language_hint: str = ""
    content_categories: tuple[str, ...] = ()
    selection_notes: tuple[str, ...] = ()
    min_score: float = 0.55


@dataclass
class RankedCandidate:
    article_id: str
    title: str
    url: str
    publisher: str
    score: float
    relevance: str
    practical_impact: str = ""
    newsworthiness: str = ""
    audience_interest: str = ""
    freshness: str = ""
    suitable: bool = False
    published_at: str = ""


@dataclass
class EditorialRanking:
    status: str
    message: str
    audience_id: str
    top: list[RankedCandidate] = field(default_factory=list)
    selected_id: str = ""
    selected: RankedCandidate | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    min_score: float = 0.0

    def as_detail(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "audience_id": self.audience_id,
            "selected_id": self.selected_id,
            "min_score": self.min_score,
            "usage": self.usage,
            "top": [
                {
                    "id": item.article_id,
                    "title": item.title,
                    "url": item.url,
                    "publisher": item.publisher,
                    "score": item.score,
                    "relevance": item.relevance,
                    "practical_impact": item.practical_impact,
                    "newsworthiness": item.newsworthiness,
                    "audience_interest": item.audience_interest,
                    "freshness": item.freshness,
                    "suitable": item.suitable,
                    "published_at": item.published_at,
                }
                for item in self.top
            ],
        }


def load_audience_profiles(path: Path | None = None) -> dict[str, AudienceProfile]:
    file_path = Path(path) if path is not None else DEFAULT_AUDIENCES_FILE
    if not file_path.is_file():
        raise ConfigurationError(f"editorial audiences file missing: {file_path}")
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigurationError("editorial audiences file must be a JSON object")
    profiles: dict[str, AudienceProfile] = {}
    for key, raw in payload.items():
        if not isinstance(raw, dict):
            continue
        profiles[key] = AudienceProfile(
            id=str(raw.get("id") or key),
            label=str(raw.get("label") or key),
            language_hint=str(raw.get("language_hint") or ""),
            content_categories=tuple(str(item) for item in (raw.get("content_categories") or [])),
            selection_notes=tuple(str(item) for item in (raw.get("selection_notes") or [])),
            min_score=float(raw.get("min_score") or 0.55),
        )
    if not profiles:
        raise ConfigurationError("editorial audiences file has no profiles")
    return profiles


def get_audience_profile(audience_id: str, *, path: Path | None = None) -> AudienceProfile:
    profiles = load_audience_profiles(path)
    if audience_id not in profiles:
        raise ConfigurationError(f"unknown editorial audience: {audience_id}")
    return profiles[audience_id]


def assign_article_ids(candidates: Sequence[Any]) -> list[dict[str, Any]]:
    """Attach stable ids (c01, c02, …) to retrieved candidates only."""

    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        article_id = f"c{index:02d}"
        published = getattr(candidate, "published_at", None)
        if isinstance(published, datetime):
            published_text = published.astimezone(timezone.utc).isoformat()
        else:
            published_text = str(published or "")
        rows.append(
            {
                "id": article_id,
                "title": str(getattr(candidate, "title", "") or ""),
                "summary": str(getattr(candidate, "summary", "") or ""),
                "url": str(getattr(candidate, "url", "") or ""),
                "publisher": str(getattr(candidate, "publisher", "") or ""),
                "published_at": published_text,
                "category": str(getattr(candidate, "category", "") or ""),
                "candidate": candidate,
            }
        )
    return rows


def build_ranking_prompt(
    articles: Sequence[Mapping[str, Any]],
    profile: AudienceProfile,
    *,
    now: datetime,
    min_score: float,
) -> str:
    catalog = [
        {
            "id": row["id"],
            "title": row["title"],
            "summary": row["summary"],
            "publisher": row["publisher"],
            "published_at": row["published_at"],
            "category": row.get("category") or "",
        }
        for row in articles
    ]
    return (
        "Rank the retrieved news articles for a short Instagram news Reel.\n"
        f"Audience profile id: {profile.id}\n"
        f"Audience label: {profile.label}\n"
        f"Language hint: {profile.language_hint}\n"
        f"Content categories: {', '.join(profile.content_categories)}\n"
        f"Selection notes: {' | '.join(profile.selection_notes)}\n"
        f"Current UTC time: {now.astimezone(timezone.utc).isoformat()}\n"
        f"Minimum suitable score: {min_score:.2f}\n\n"
        "Rules:\n"
        "- Select only from the supplied article ids.\n"
        "- Never invent article ids or URLs.\n"
        "- Do not require the article to mention Iran or Iranians.\n"
        "- Score each chosen article from 0.0 to 1.0 using relevance, practical impact, "
        "newsworthiness, audience interest, and freshness.\n"
        "- Mark suitable=true only when the story is good enough to publish for this audience.\n"
        "- If none are suitable, set selected_id to null and explain in rejection_reason.\n"
        "- Return at most three rankings, best first.\n\n"
        "Reply with one JSON object:\n"
        "{\n"
        '  "rankings": [\n'
        "    {\n"
        '      "id": "c01",\n'
        '      "score": 0.0,\n'
        '      "relevance": "",\n'
        '      "practical_impact": "",\n'
        '      "newsworthiness": "",\n'
        '      "audience_interest": "",\n'
        '      "freshness": "",\n'
        '      "suitable": false\n'
        "    }\n"
        "  ],\n"
        '  "selected_id": "c01" or null,\n'
        '  "rejection_reason": ""\n'
        "}\n\n"
        f"Articles:\n{json.dumps(catalog, ensure_ascii=False, indent=2)}\n"
    )


def parse_ranking_response(
    payload: Mapping[str, Any],
    articles_by_id: Mapping[str, Mapping[str, Any]],
    *,
    min_score: float,
) -> EditorialRanking:
    """Validate model output against the retrieved id set."""

    known = set(articles_by_id)
    raw_rankings = payload.get("rankings")
    if not isinstance(raw_rankings, list):
        raise GroundingError("editorial ranking response missing rankings list")

    ranked: list[RankedCandidate] = []
    seen: set[str] = set()
    for item in raw_rankings:
        if not isinstance(item, Mapping):
            continue
        article_id = str(item.get("id") or "").strip()
        if not article_id:
            continue
        if article_id not in known:
            raise GroundingError(f"editorial ranking invented article id: {article_id}")
        if article_id in seen:
            continue
        seen.add(article_id)
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError) as exc:
            raise GroundingError(f"editorial ranking score invalid for {article_id}") from exc
        score = max(0.0, min(1.0, score))
        source = articles_by_id[article_id]
        ranked.append(
            RankedCandidate(
                article_id=article_id,
                title=str(source["title"]),
                url=str(source["url"]),
                publisher=str(source["publisher"]),
                score=score,
                relevance=str(item.get("relevance") or "").strip(),
                practical_impact=str(item.get("practical_impact") or "").strip(),
                newsworthiness=str(item.get("newsworthiness") or "").strip(),
                audience_interest=str(item.get("audience_interest") or "").strip(),
                freshness=str(item.get("freshness") or "").strip(),
                suitable=bool(item.get("suitable")) and score >= min_score,
                published_at=str(source.get("published_at") or ""),
            )
        )

    ranked.sort(key=lambda row: row.score, reverse=True)
    top = ranked[:3]
    selected_raw = payload.get("selected_id")
    selected_id = str(selected_raw).strip() if selected_raw not in {None, ""} else ""
    if selected_id and selected_id not in known:
        raise GroundingError(f"editorial ranking invented selected_id: {selected_id}")

    selected: RankedCandidate | None = None
    if selected_id:
        for item in ranked:
            if item.article_id == selected_id:
                selected = item
                break
        if selected is None:
            source = articles_by_id[selected_id]
            selected = RankedCandidate(
                article_id=selected_id,
                title=str(source["title"]),
                url=str(source["url"]),
                publisher=str(source["publisher"]),
                score=0.0,
                relevance="",
                suitable=False,
                published_at=str(source.get("published_at") or ""),
            )

    rejection = str(payload.get("rejection_reason") or "").strip()
    if selected is not None and selected.suitable and selected.score >= min_score:
        if selected not in top:
            top = [selected, *[item for item in top if item.article_id != selected.article_id]][:3]
        return EditorialRanking(
            status="selected",
            message="",
            audience_id="",
            top=top,
            selected_id=selected.article_id,
            selected=selected,
            raw=dict(payload),
            min_score=min_score,
        )

    message = rejection or "no suitable article for this audience"
    return EditorialRanking(
        status="rejected",
        message=message,
        audience_id="",
        top=top,
        selected_id="",
        selected=None,
        raw=dict(payload),
        min_score=min_score,
    )


def prepare_ranking_request(
    candidates: Sequence[Any],
    *,
    audience_id: str = "iranians_in_germany",
    audiences_file: Path | None = None,
    min_score: float | None = None,
    now: datetime | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Build prompt + usage estimate without calling OpenAI."""

    if not candidates:
        raise GroundingError("no retrieved articles to rank")
    profile = get_audience_profile(audience_id, path=audiences_file)
    threshold = float(min_score if min_score is not None else profile.min_score)
    moment = now or datetime.now(timezone.utc)
    rows = assign_article_ids(candidates)
    chosen_model = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    prompt = build_ranking_prompt(rows, profile, now=moment, min_score=threshold)
    return {
        "profile": profile,
        "min_score": threshold,
        "model": chosen_model,
        "rows": rows,
        "prompt": prompt,
        "usage_estimate": estimate_ranking_usage(prompt, model=chosen_model),
    }


def rank_retrieved_articles(
    candidates: Sequence[Any],
    *,
    audience_id: str = "iranians_in_germany",
    audiences_file: Path | None = None,
    min_score: float | None = None,
    now: datetime | None = None,
    model: str | None = None,
    complete: CompleteFn | None = None,
    api_key: str | None = None,
    transport=None,
) -> EditorialRanking:
    """Rank already-retrieved candidates. Never invents URLs."""

    if not candidates:
        return EditorialRanking(
            status="rejected",
            message="no retrieved articles to rank",
            audience_id=audience_id,
        )
    prepared = prepare_ranking_request(
        candidates,
        audience_id=audience_id,
        audiences_file=audiences_file,
        min_score=min_score,
        now=now,
        model=model,
    )
    threshold = float(prepared["min_score"])
    rows = prepared["rows"]
    by_id = {row["id"]: row for row in rows}
    prompt = prepared["prompt"]
    chosen_model = prepared["model"]
    usage = dict(prepared["usage_estimate"])
    completer = complete or complete_chat
    kwargs: dict[str, Any] = {"model": chosen_model}
    if complete is None:
        kwargs["api_key"] = api_key
        kwargs["transport"] = transport
    payload = completer(prompt, {"audience_id": audience_id, "article_ids": list(by_id)}, **kwargs)
    if not isinstance(payload, Mapping):
        raise GroundingError("editorial ranking response must be a JSON object")
    # Injected completes may return either the assistant JSON or {"content": ..., "usage": ...}.
    if "rankings" in payload:
        content = payload
        if isinstance(payload.get("_usage"), Mapping):
            usage = usage_from_openai_payload({"usage": payload["_usage"]}, model=chosen_model)
    elif isinstance(payload.get("content"), Mapping):
        content = payload["content"]
        usage = usage_from_openai_payload(payload, model=chosen_model) if payload.get("usage") else usage
    else:
        content = payload
    result = parse_ranking_response(content, by_id, min_score=threshold)
    result.audience_id = audience_id
    result.usage = usage
    result.min_score = threshold
    return result
