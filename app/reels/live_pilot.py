"""Controlled ONE-run live Persian Reel (Phase 7).

Estimates OpenAI + ElevenLabs cost before any paid call. Live execution requires
an explicit ``approve_paid`` flag for this single run. Does not enable Cron,
Instagram publishing, or global ``REEL_PAID_GENERATION``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.reels.pilot import PilotResult, narration_from_story, new_run_id, run_persian_reel_pilot
from app.reels.voice import ARAN_VOICE, ELEVENLABS_USD_PER_CHAR, prepare_spoken
from app.services.llm.openai_script import DEFAULT_MODEL, complete_chat
from app.services.llm.persian_script import (
    generate_persian_story_package,
    write_story_package,
)

# Published OpenAI gpt-4o-mini Chat Completions rates (USD per 1M tokens).
# Not yet a reel-cost-tracking catalog row for chat; treat as an external estimate.
OPENAI_INPUT_USD_PER_1M = 0.15
OPENAI_OUTPUT_USD_PER_1M = 0.60
CHARS_PER_TOKEN_EST = 4.0
PER_REEL_CAP_USD = 0.50


@dataclass
class LiveCostEstimate:
    status: str
    total_usd: float | None
    under_cap: bool
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_usd": self.total_usd,
            "under_cap": self.under_cap,
            "per_reel_cap_usd": PER_REEL_CAP_USD,
            "detail": self.detail,
            "note": "An estimate is not a bill. Measured usage replaces the estimate after the call.",
        }


def estimate_live_reel_cost(
    *,
    narration_chars: int,
    prompt_chars: int = 3500,
    expected_output_chars: int = 2500,
    openai_model: str = DEFAULT_MODEL,
) -> LiveCostEstimate:
    """Estimate ONE OpenAI script call + ONE ElevenLabs Aran narration."""

    spoken_chars = max(int(narration_chars), 1)
    eleven_usd = round(spoken_chars * ELEVENLABS_USD_PER_CHAR, 6)
    input_tokens = max(int(prompt_chars / CHARS_PER_TOKEN_EST), 1)
    output_tokens = max(int(expected_output_chars / CHARS_PER_TOKEN_EST), 1)
    openai_usd = round(
        input_tokens * OPENAI_INPUT_USD_PER_1M / 1_000_000
        + output_tokens * OPENAI_OUTPUT_USD_PER_1M / 1_000_000,
        6,
    )
    total = round(openai_usd + eleven_usd, 6)
    detail = {
        "openai": {
            "model": openai_model,
            "billing": "external_published_estimate",
            "input_tokens_est": input_tokens,
            "output_tokens_est": output_tokens,
            "usd": openai_usd,
            "source": "https://openai.com/api/pricing (gpt-4o-mini)",
        },
        "elevenlabs": {
            "model": "eleven_v4",
            "voice_id": ARAN_VOICE,
            "characters": spoken_chars,
            "usd": eleven_usd,
            "usd_per_1000_chars": 0.08,
            "source": "https://elevenlabs.io/pricing/api",
        },
        "remotion": {"usd": 0.0, "billing": "local_unbilled"},
        "images": {"usd": 0.0, "billing": "local_graphics_or_commons_cache"},
    }
    return LiveCostEstimate(
        status="estimated",
        total_usd=total,
        under_cap=total <= PER_REEL_CAP_USD,
        detail=detail,
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _assets_from_json(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = _load_json(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("assets"), list):
        return [item for item in payload["assets"] if isinstance(item, dict)]
    return []


def run_live_persian_reel(
    *,
    fact_pack: Path,
    editorial_review: Path,
    out_dir: Path | None = None,
    assets_json: Path | None = None,
    approve_paid: bool = False,
    estimate_only: bool = False,
    database_path: Path | None = None,
    planned_narration_chars: int = 520,
) -> dict[str, Any]:
    """Estimate, optionally generate script + Aran audio + Remotion for ONE story."""

    run_id = new_run_id(prefix="first-live-news")
    destination = Path(out_dir) if out_dir is not None else Path("storage/generated/pilot") / run_id
    destination.mkdir(parents=True, exist_ok=True)

    pack = _load_json(fact_pack)
    editorial = _load_json(editorial_review)
    write_story_package(pack, destination / "fact_pack.json")
    write_story_package(editorial, destination / "editorial_review.json")

    estimate = estimate_live_reel_cost(narration_chars=planned_narration_chars)
    estimate_path = destination / "cost_estimate.json"
    estimate_path.write_text(json.dumps(estimate.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload: dict[str, Any] = {
        "run_id": run_id,
        "out_dir": str(destination),
        "estimate": estimate.to_dict(),
        "estimate_path": str(estimate_path),
        "approve_paid": bool(approve_paid),
        "cron_enabled": False,
        "instagram_publish_enabled": False,
        "global_paid_generation_enabled": False,
    }

    if estimate_only or not approve_paid:
        payload["status"] = "awaiting_approval" if not approve_paid else "estimate_only"
        payload["message"] = (
            "Paid OpenAI/ElevenLabs calls are blocked until --approve-paid is passed for this ONE run."
            if not approve_paid
            else "Estimate only; no paid calls."
        )
        (destination / "pilot_report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return payload

    if not estimate.under_cap:
        payload["status"] = "rejected"
        payload["message"] = f"estimate {estimate.total_usd} exceeds cap {PER_REEL_CAP_USD}"
        (destination / "pilot_report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return payload

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        payload["status"] = "rejected"
        payload["message"] = "OPENAI_API_KEY is missing"
        return payload
    if not os.environ.get("ELEVENLABS_API_KEY", "").strip():
        payload["status"] = "rejected"
        payload["message"] = "ELEVENLABS_API_KEY is missing"
        return payload

    model = os.environ.get("OPENAI_SCRIPT_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    def script_complete(prompt: str, context):
        return complete_chat(prompt, context, model=model)

    story = generate_persian_story_package(pack, editorial, complete=script_complete)
    write_story_package(story, destination / "story_package.json")
    narration = narration_from_story(story)
    (destination / "narration.txt").write_text(narration + "\n", encoding="utf-8")

    # Refresh estimate with the actual script length before voice.
    actual_estimate = estimate_live_reel_cost(
        narration_chars=len(prepare_spoken(narration)),
        prompt_chars=max(len(json.dumps(pack, ensure_ascii=False)), 1),
        expected_output_chars=max(len(json.dumps(story, ensure_ascii=False)), 1),
        openai_model=model,
    )
    estimate_path.write_text(
        json.dumps(actual_estimate.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not actual_estimate.under_cap:
        payload.update(
            {
                "status": "rejected",
                "message": f"post-script estimate {actual_estimate.total_usd} exceeds cap {PER_REEL_CAP_USD}",
                "estimate": actual_estimate.to_dict(),
                "story_package": str(destination / "story_package.json"),
            }
        )
        (destination / "pilot_report.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return payload

    assets = _assets_from_json(assets_json)
    result: PilotResult = run_persian_reel_pilot(
        out_dir=destination,
        run_id=run_id,
        story_package=story,
        assets=assets,
        voice_approved=True,
        require_live_voice=True,
        database_path=database_path,
        overwrite=True,
    )
    payload.update(
        {
            "status": result.status,
            "message": result.message,
            "estimate": actual_estimate.to_dict(),
            "story_package": result.story_package_path,
            "narration": result.narration_path,
            "audio": result.audio_path,
            "video": result.video_path,
            "contact_sheet": result.contact_sheet_path,
            "qa_report": result.qa_report_path,
            "report": result.report_path,
            "paid_api_calls": True,
            "voice": {
                "provider": "elevenlabs",
                "voice_id": ARAN_VOICE,
                "model_id": "eleven_v4",
                "language": "fa",
                "speed": 1.0,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    (destination / "live_pilot_report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload
