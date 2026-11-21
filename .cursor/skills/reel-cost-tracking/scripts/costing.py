"""Estimate and gate Reel spend. This does not call a provider."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKING = {"unknown", "incomplete", "unavailable", "unsupported_language", "license_unverified"}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_pricing(path: Path | None = None) -> dict:
    return load_json(path or ROOT / "config" / "pricing.json")


def load_budget(path: Path | None = None) -> dict:
    return load_json(path or ROOT / "config" / "budget.json")


def find_price(pricing: dict, provider: str, model: str) -> dict | None:
    for entry in pricing["entries"]:
        if entry["provider"] == provider and entry["model"] == model:
            return entry
    return None


def _attempts(request: dict, max_attempts: int) -> tuple[int, str | None]:
    attempts = int(request.get("attempts", 1))
    if attempts < 1 or attempts > max_attempts:
        return attempts, f"attempts must be 1..{max_attempts}"
    return attempts, None


def quote_request(entry: dict | None, request: dict, *, max_attempts: int) -> dict:
    provider = request["provider"]
    model = request["model"]
    attempts, attempt_error = _attempts(request, max_attempts)
    base = {
        "provider": provider,
        "model": model,
        "attempts": attempts,
        "cache_hit": bool(request.get("cache_hit")),
        "failed_requests": int(request.get("failed_requests", 0)),
    }
    if attempt_error:
        return {**base, "status": "incomplete", "usd": None, "reason": attempt_error}
    if entry is None:
        return {**base, "status": "unknown", "usd": None, "reason": "no catalog entry"}
    billing = entry["billing"]
    if request.get("cache_hit"):
        return {**base, "status": "cached", "usd": 0.0, "cost_kind": "estimate", "reason": "cached output is not billed again"}
    if billing == "unbilled":
        return {**base, "status": "unbilled", "usd": 0.0, "cost_kind": "unbilled", "source": entry.get("source")}
    if billing == "unsupported_language":
        return {**base, "status": "unsupported_language", "usd": None, "reason": entry.get("notes")}
    if billing == "unavailable":
        return {**base, "status": "unavailable", "usd": None, "reason": entry.get("notes")}
    if billing == "unknown":
        return {**base, "status": "unknown", "usd": None, "reason": entry.get("notes")}
    if billing == "per_character":
        if request.get("voice_rate_confirmed") is False:
            return {**base, "status": "incomplete", "usd": None, "reason": "voice rate was not confirmed against the catalog"}
        catalog_per_1000 = float(entry["usd_per_unit"]) * 1000
        custom = request.get("voice_fiat_rate_per_1000")
        if custom is not None and abs(float(custom) - catalog_per_1000) > 1e-9:
            return {
                **base,
                "status": "unknown",
                "usd": None,
                "reason": "this voice publishes a custom rate that is not in the catalog",
            }
        characters = int(request["characters"]) * attempts
        usd = round(characters * float(entry["usd_per_unit"]), 6)
        return {**base, "status": "estimated", "usd": usd, "cost_kind": "estimate", "characters": characters, "source": entry.get("source")}
    if billing == "documented_output_estimate":
        if request.get("quality") == "auto" or request.get("size") == "auto":
            return {**base, "status": "incomplete", "usd": None, "reason": "quality or size auto has no fixed token count"}
        if request.get("size") != entry.get("size") or request.get("quality") != entry.get("quality"):
            return {**base, "status": "incomplete", "usd": None, "reason": "the calculator cell covers only the documented size and quality"}
        if "text_input_tokens" not in request or "image_input_tokens" not in request:
            return {
                **base,
                "status": "incomplete",
                "usd": None,
                "reason": "the published image-output estimate excludes text and image input tokens",
            }
        if int(request.get("images", 1)) != 1:
            return {**base, "status": "incomplete", "usd": None, "reason": "the calculator cell covers one image"}
        if "image_output_tokens" in request:
            output_tokens = int(request["image_output_tokens"])
            price_basis = "measured_usage"
        else:
            output_tokens = int(entry["output_tokens"])
            price_basis = "official_calculator"
        partial = int(request.get("partial_images") or 0) * 100 * attempts
        output_tokens *= attempts
        text_tokens = int(request["text_input_tokens"]) * attempts
        image_input_tokens = int(request["image_input_tokens"]) * attempts
        usd = (
            (output_tokens + partial) * float(entry["usd_per_1m_image_output_tokens"])
            + text_tokens * float(entry["usd_per_1m_text_input_tokens"])
            + image_input_tokens * float(entry["usd_per_1m_image_input_tokens"])
        ) / 1_000_000
        return {
            **base,
            "status": "estimated",
            "usd": round(usd, 6),
            "cost_kind": "estimate",
            "price_basis": price_basis,
            "ceiling": False,
            "image_output_tokens": output_tokens + partial,
            "text_input_tokens": text_tokens,
            "image_input_tokens": image_input_tokens,
            "source": entry.get("source"),
            "uncertainty": "This is an estimate, not a spending ceiling. Actual usage can differ and must be read from the response.",
        }
    if billing == "incomplete_without_image_output_tokens":
        if request.get("quality") == "auto":
            return {**base, "status": "incomplete", "usd": None, "reason": "quality auto has no fixed token count"}
        if "image_output_tokens" not in request or "text_input_tokens" not in request or "image_input_tokens" not in request:
            return {**base, "status": "incomplete", "usd": None, "reason": "image output tokens are unknown before the call"}
        if int(request.get("images", 1)) != 1:
            return {**base, "status": "incomplete", "usd": None, "reason": "a token quote covers one measured image"}
        output_tokens = int(request["image_output_tokens"]) * attempts
        text_tokens = int(request["text_input_tokens"]) * attempts
        image_input_tokens = int(request["image_input_tokens"]) * attempts
        partial = int(request.get("partial_images") or 0) * 100 * attempts
        usd = (
            output_tokens * float(entry["usd_per_1m_image_output_tokens"])
            + partial * float(entry["usd_per_1m_image_output_tokens"])
            + text_tokens * float(entry["usd_per_1m_text_input_tokens"])
            + image_input_tokens * float(entry["usd_per_1m_image_input_tokens"])
        ) / 1_000_000
        return {
            **base,
            "status": "estimated",
            "usd": round(usd, 6),
            "cost_kind": "estimate",
            "image_output_tokens": output_tokens + partial,
            "text_input_tokens": text_tokens,
            "source": entry.get("source"),
            "uncertainty": "This uses measured tokens. It is not a published per-image price.",
        }
    if billing == "per_image_output_equivalent":
        images = int(request["images"]) * attempts
        usd = round(images * float(entry["usd_per_image"]), 6)
        return {
            **base,
            "status": "estimated",
            "usd": usd,
            "cost_kind": "estimate",
            "images": images,
            "uncertainty": "Prompt input tokens are not included in this published per-image equivalent.",
            "source": entry.get("source"),
        }
    if billing == "incomplete_without_audio_tokens":
        if "audio_output_tokens" not in request or "text_input_tokens" not in request:
            return {**base, "status": "incomplete", "usd": None, "reason": "audio output tokens are unknown before the call"}
        usd = (
            int(request["text_input_tokens"]) * attempts * float(entry["usd_per_1m_text_input_tokens"])
            + int(request["audio_output_tokens"]) * attempts * float(entry["usd_per_1m_audio_output_tokens"])
        ) / 1_000_000
        return {**base, "status": "estimated", "usd": round(usd, 6), "cost_kind": "estimate", "source": entry.get("source")}
    if billing == "license_dependent":
        license_name = request.get("license")
        renders = int(request.get("renders", 1)) * attempts
        if license_name == "evaluation":
            return {**base, "status": "evaluation", "usd": 0.0, "cost_kind": "unbilled", "reason": "evaluation is not a production render"}
        if license_name == "free_small_team":
            return {**base, "status": "unbilled", "usd": 0.0, "cost_kind": "unbilled", "reason": entry.get("notes")}
        if license_name == "company_automator":
            marginal = round(renders * float(entry["usd_per_render"]), 6)
            return {
                **base,
                "status": "estimated",
                "usd": marginal,
                "cost_kind": "estimate",
                "monthly_minimum_usd": entry["monthly_minimum_usd"],
                "source": entry.get("source"),
            }
        return {**base, "status": "license_unverified", "usd": None, "reason": entry.get("notes")}
    return {**base, "status": "unknown", "usd": None, "reason": f"unsupported billing {billing}"}


def estimate_plan(plan: dict, pricing: dict, budget: dict) -> dict:
    lines = [
        quote_request(find_price(pricing, item["provider"], item["model"]), item, max_attempts=int(budget["max_attempts"]))
        for item in plan["requests"]
    ]
    known = [line["usd"] for line in lines if isinstance(line.get("usd"), (int, float))]
    blocking = [line for line in lines if line["status"] in BLOCKING]
    return {
        "reel_id": plan["reel_id"],
        "currency": pricing["currency"],
        "catalog_version": pricing["catalog_version"],
        "estimated_usd": round(sum(known), 6),
        "lines": lines,
        "blocking": blocking,
        "budget_guaranteed": False,
    }


def month_spend(ledger_path: Path, month: str) -> tuple[float, bool]:
    if not ledger_path.exists():
        return 0.0, False
    total = 0.0
    saw_unbilled = False
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not str(row.get("recorded_at", "")).startswith(month):
            continue
        if row.get("cost_kind") == "unbilled":
            saw_unbilled = True
            continue
        if row.get("cost_kind") in {"estimate", "actual"}:
            total += float(row["usd"])
            if row.get("cost_kind") != "actual":
                saw_unbilled = True
    return round(total, 6), saw_unbilled


def gate(estimate: dict, budget: dict, *, spent_usd: float) -> dict:
    reasons = [f"{line['provider']}/{line['model']}: {line.get('reason') or line['status']}" for line in estimate["blocking"]]
    per_reel = float(budget["per_reel_max_usd"])
    monthly = float(budget["monthly_target_usd"])
    if estimate["estimated_usd"] > per_reel:
        reasons.append(f"estimate ${estimate['estimated_usd']:.4f} exceeds the ${per_reel:.2f} per-Reel target")
    experiment_cap = budget.get("experiment_max_usd")
    if experiment_cap is not None and estimate["estimated_usd"] > float(experiment_cap):
        reasons.append(f"estimate ${estimate['estimated_usd']:.4f} exceeds the ${float(experiment_cap):.2f} experiment cap")
    if spent_usd + estimate["estimated_usd"] > monthly:
        reasons.append(f"month-to-date ${spent_usd:.4f} plus this Reel exceeds the ${monthly:.2f} monthly target")
    minimums = [line.get("monthly_minimum_usd") for line in estimate["lines"] if line.get("monthly_minimum_usd")]
    for minimum in minimums:
        if float(minimum) > monthly:
            reasons.append(f"a provider minimum of ${float(minimum):.2f} per month is above the ${monthly:.2f} target")
    return {
        "allowed": not reasons,
        "reasons": reasons,
        "estimated_usd": estimate["estimated_usd"],
        "spent_usd": spent_usd,
        "remaining_monthly_usd": round(monthly - spent_usd, 6),
        "per_reel_max_usd": per_reel,
        "budget_guaranteed": False,
    }


def voice_request(
    *,
    characters: int,
    voice_rate_confirmed: bool,
    voice_fiat_rate_per_1000: float | None = None,
) -> dict:
    voice = {
        "provider": "elevenlabs",
        "model": "eleven_v4",
        "characters": characters,
        "attempts": 1,
        "voice_rate_confirmed": voice_rate_confirmed,
    }
    if voice_fiat_rate_per_1000 is not None:
        voice["voice_fiat_rate_per_1000"] = voice_fiat_rate_per_1000
    return voice


def image_request(
    *,
    image_output_tokens: int | None = None,
    text_input_tokens: int | None = None,
    image_input_tokens: int | None = None,
) -> dict:
    image: dict = {
        "provider": "openai",
        "model": "gpt-image-2.5-sunburst",
        "images": 1,
        "size": "1024x1536",
        "quality": "high",
        "attempts": 1,
    }
    if image_output_tokens is not None:
        image["image_output_tokens"] = image_output_tokens
    if text_input_tokens is not None:
        image["text_input_tokens"] = text_input_tokens
    if image_input_tokens is not None:
        image["image_input_tokens"] = image_input_tokens
    return image


def authorize_plan(plan: dict, *, ledger_path: Path | None = None, month: str | None = None) -> dict:
    """Apply the Reel budget to one plan. Incomplete lines stay blocked."""

    pricing = load_pricing()
    budget = load_budget()
    spent = 0.0
    if ledger_path is not None:
        spent_month = month or datetime.now(timezone.utc).strftime("%Y-%m")
        spent, _uncertain = month_spend(ledger_path, spent_month)
    estimate = estimate_plan(plan, pricing, budget)
    decision = gate(estimate, budget, spent_usd=spent)
    decision["experiment_max_usd"] = budget.get("experiment_max_usd")
    decision["per_reel_max_usd"] = budget["per_reel_max_usd"]
    return {"plan": plan, "estimate": estimate, "decision": decision}


def authorize_voice_test(
    *,
    characters: int,
    voice_rate_confirmed: bool,
    voice_fiat_rate_per_1000: float | None = None,
    ledger_path: Path | None = None,
    month: str | None = None,
) -> dict:
    """Price ElevenLabs alone. An unpriced OpenAI image is not part of this plan."""

    plan = {
        "reel_id": "voice-quality-2026-11-19",
        "requests": [
            voice_request(
                characters=characters,
                voice_rate_confirmed=voice_rate_confirmed,
                voice_fiat_rate_per_1000=voice_fiat_rate_per_1000,
            )
        ],
    }
    return authorize_plan(plan, ledger_path=ledger_path, month=month)


def authorize_image_test(
    *,
    image_output_tokens: int | None = None,
    text_input_tokens: int | None = None,
    image_input_tokens: int | None = None,
    ledger_path: Path | None = None,
    month: str | None = None,
) -> dict:
    """Price one OpenAI image alone. Missing output tokens stay incomplete."""

    plan = {
        "reel_id": "image-quality-2026-11-19",
        "requests": [
            image_request(
                image_output_tokens=image_output_tokens,
                text_input_tokens=text_input_tokens,
                image_input_tokens=image_input_tokens,
            )
        ],
    }
    return authorize_plan(plan, ledger_path=ledger_path, month=month)


def project_month(per_reel_usd: float, reels: int = 120) -> dict:
    return {"reels": reels, "per_reel_usd": per_reel_usd, "month_usd": round(per_reel_usd * reels, 6)}


def record(ledger_path: Path, row: dict) -> None:
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {"recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **row}
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(stamped, ensure_ascii=False) + "\n")
