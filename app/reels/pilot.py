"""Controlled end-to-end Persian Reel pilot (Phases 3–5).

Offline by default: accepts a story package and local MP3, renders with Remotion,
writes QA artifacts into an isolated pilot directory, and never enables Cron or
Instagram publishing. OpenAI and ElevenLabs stay behind injectable mocks unless
the caller explicitly supplies live transports/approvals.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.reels.pipeline import Candidate
from app.reels.qa import technical_qa_report
from app.reels.render import RenderError, make_silent_mp3, render_data_reel
from app.reels.store import ReelStore, utc_now
from app.reels.voice import ARAN_VOICE, narrate_persian
from app.services.llm.persian_script import (
    build_editorial_brief,
    build_fact_pack,
    generate_persian_story_package,
    write_story_package,
)

DEFAULT_PILOT_ROOT = Path("storage/generated/pilot")


@dataclass
class PilotResult:
    status: str
    message: str = ""
    run_id: str = ""
    out_dir: str = ""
    story_package_path: str = ""
    narration_path: str = ""
    audio_path: str = ""
    video_path: str = ""
    contact_sheet_path: str = ""
    qa_report_path: str = ""
    report_path: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def narration_from_story(story: dict[str, Any]) -> str:
    """Join scene narrations in order — the single source of spoken text for the pilot."""

    parts: list[str] = []
    for scene in story.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        text = str(scene.get("narration") or "").strip()
        if text:
            parts.append(text)
    return " ".join(parts)


def new_run_id(prefix: str = "e2e") -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"


def _refuse_overwrite(path: Path, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise RenderError(f"refusing to overwrite existing pilot artifact: {path}")


def run_persian_reel_pilot(
    *,
    out_dir: Path | None = None,
    run_id: str | None = None,
    story_package: Path | dict[str, Any] | None = None,
    audio_path: Path | None = None,
    assets: list[dict[str, Any]] | None = None,
    candidate: Candidate | None = None,
    checked: dict[str, Any] | None = None,
    script_complete: Callable[..., Any] | None = None,
    voice_transport: Callable[..., Any] | None = None,
    voice_approved: bool = False,
    render_runner: Callable[..., Any] | None = None,
    database_path: Path | None = None,
    overwrite: bool = False,
    skip_render: bool = False,
) -> PilotResult:
    """Run one controlled pilot from story (or mocked script) through QA.

    Paid providers are never called unless the caller injects a live transport and
    sets ``voice_approved`` for ElevenLabs. Cron and publishing are not touched.
    """

    rid = run_id or new_run_id()
    destination = Path(out_dir) if out_dir is not None else DEFAULT_PILOT_ROOT / rid
    destination.mkdir(parents=True, exist_ok=True)
    story_path = destination / "story_package.json"
    narration_path = destination / "narration.txt"
    final_audio = destination / "audio" / "narration.mp3"
    video_path = destination / "reel.mp4"
    contact_sheet_path = destination / "contact-sheet.jpg"
    qa_path = destination / "qa_technical.json"

    try:
        # --- Phase 3: story package ---------------------------------------------
        if story_package is None:
            if candidate is None or script_complete is None:
                return PilotResult(
                    status="rejected",
                    message="story_package or (candidate + script_complete) is required",
                    run_id=rid,
                    out_dir=str(destination),
                )
            fact_pack = build_fact_pack(
                title=candidate.title,
                summary=candidate.summary,
                url=candidate.url,
                publisher=candidate.publisher,
                published_at=candidate.published_at,
                excerpt=str((checked or {}).get("excerpt") or candidate.summary),
            )
            editorial = build_editorial_brief(fact_pack, title=candidate.title, summary=candidate.summary)
            story = generate_persian_story_package(fact_pack, editorial, complete=script_complete)
            write_story_package(fact_pack, destination / "fact_pack.json")
            write_story_package(editorial, destination / "editorial_review.json")
        elif isinstance(story_package, dict):
            story = dict(story_package)
        else:
            story = json.loads(Path(story_package).read_text(encoding="utf-8"))

        _refuse_overwrite(story_path, overwrite=overwrite)
        write_story_package(story, story_path)

        narration = narration_from_story(story)
        if not narration:
            return PilotResult(
                status="rejected",
                message="story has no narration",
                run_id=rid,
                out_dir=str(destination),
            )
        narration_path.write_text(narration + "\n", encoding="utf-8")

        # --- Phase 4: audio -----------------------------------------------------
        audio_dir = destination / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        _refuse_overwrite(final_audio, overwrite=overwrite)

        if audio_path is not None:
            if not Path(audio_path).is_file():
                return PilotResult(
                    status="rejected",
                    message=f"audio missing: {audio_path}",
                    run_id=rid,
                    out_dir=str(destination),
                )
            shutil.copy2(audio_path, final_audio)
            audio_meta = {
                "path": str(final_audio),
                "provider": "fixture",
                "voice_id": ARAN_VOICE,
                "model_id": "eleven_v4",
                "speed": 1.0,
                "duration_seconds": None,
                "characters": len(narration),
                "usd": 0.0,
                "display_text": narration,
                "spoken_text": narration,
                "espeak_used": False,
            }
        elif voice_transport is not None or voice_approved:
            audio_meta = narrate_persian(
                narration,
                ARAN_VOICE,
                out_path=final_audio,
                approved=voice_approved,
                transport=voice_transport,
                ledger_path=destination / "cost-ledger" / "usage.jsonl",
            )
            if audio_meta.get("display_text") != narration:
                return PilotResult(
                    status="failed",
                    message="voice stage returned a different display narration",
                    run_id=rid,
                    out_dir=str(destination),
                    story_package_path=str(story_path),
                    narration_path=str(narration_path),
                )
        else:
            seconds = float(story.get("duration_seconds") or 0) or sum(
                float(scene.get("duration_seconds") or 0)
                for scene in story.get("scenes") or []
                if isinstance(scene, dict)
            )
            make_silent_mp3(final_audio, seconds=max(seconds, 1.0))
            audio_meta = {
                "path": str(final_audio),
                "provider": "silent-fixture",
                "voice_id": ARAN_VOICE,
                "model_id": "eleven_v4",
                "speed": 1.0,
                "duration_seconds": seconds,
                "characters": len(narration),
                "usd": 0.0,
                "display_text": narration,
                "spoken_text": narration,
                "espeak_used": False,
            }

        manifest = {
            "provider": audio_meta.get("provider"),
            "model": audio_meta.get("model_id") or "eleven_v4",
            "model_id": audio_meta.get("model_id") or "eleven_v4",
            "voice_id": audio_meta.get("voice_id") or ARAN_VOICE,
            "language_code": "fa",
            "speed": float(audio_meta.get("speed") or 1.0),
            "espeak_used": False,
            "narration": narration,
            "path": str(final_audio),
            "characters": audio_meta.get("characters"),
        }
        (audio_dir / "voice_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        # --- Phase 5: Remotion --------------------------------------------------
        probe: dict[str, Any] = {}
        render_detail: dict[str, Any] = {}
        if skip_render:
            status = "scripted"
            message = "render skipped"
        else:
            _refuse_overwrite(video_path, overwrite=overwrite)
            render_detail = render_data_reel(
                story,
                final_audio,
                out_path=video_path,
                assets=assets or [],
                overwrite=overwrite,
                runner=render_runner,
                render_id=rid,
            )
            probe = render_detail.get("probe") or {}
            if render_detail.get("problems"):
                status = "qa_failed"
                message = "; ".join(render_detail["problems"])
            else:
                status = "qa_passed"
                message = ""

        # --- Technical QA + contact sheet --------------------------------------
        qa_report: dict[str, Any] = {}
        if video_path.is_file():
            qa_report = technical_qa_report(
                video_path,
                contact_sheet=contact_sheet_path,
                narration=narration,
                min_seconds=1.0,
                max_seconds=900.0,
            )
            qa_path.write_text(json.dumps(qa_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if not qa_report.get("technical_pass"):
                status = "qa_failed"
                message = "; ".join(qa_report.get("problems") or ["technical qa failed"])

        report = {
            "run_id": rid,
            "status": status,
            "message": message,
            "out_dir": str(destination),
            "story_package": str(story_path),
            "narration": narration,
            "narration_path": str(narration_path),
            "audio": str(final_audio),
            "voice_manifest": str(audio_dir / "voice_manifest.json"),
            "video": str(video_path) if video_path.is_file() else "",
            "contact_sheet": str(contact_sheet_path) if contact_sheet_path.is_file() else "",
            "qa_report": str(qa_path) if qa_path.is_file() else "",
            "probe": probe,
            "assets": assets or [],
            "cron_enabled": False,
            "instagram_publish_enabled": False,
            "paid_api_calls": bool(voice_approved and audio_path is None and voice_transport is None),
        }
        report_path = destination / "pilot_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        if database_path is not None and video_path.is_file():
            store = ReelStore(Path(database_path))
            store.migrate()
            stamp = utc_now()
            store.upsert_reel(
                {
                    "reel_id": rid,
                    "story_fingerprint": rid,
                    "target_page": "almanyar",
                    "title": str(story.get("headline") or rid),
                    "category": "pilot",
                    "affected_audience": str(story.get("audience") or ""),
                    "editorial_angle": str(story.get("headline") or ""),
                    "narration_fa": narration,
                    "caption_fa": str((story.get("scenes") or [{}])[0].get("on_screen_text") or "")
                    if story.get("scenes")
                    else "",
                    "storyboard_json": json.dumps(story.get("scenes") or [], ensure_ascii=False),
                    "video_path": str(video_path),
                    "duration_seconds": probe.get("duration_seconds"),
                    "width": probe.get("width"),
                    "height": probe.get("height"),
                    "checksum_sha256": probe.get("checksum_sha256"),
                    "local_status": status,
                    "production_delivery_id": None,
                    "scheduled_for": None,
                    "facts_checked_at": stamp,
                    "generation_started_at": stamp,
                    "generation_finished_at": stamp,
                    "error_message": message,
                    "retry_count": 0,
                    "created_at": stamp,
                    "updated_at": stamp,
                }
            )
            store.add_audio(rid, audio_meta)
            for asset in assets or []:
                store.add_asset(rid, asset)
            store.add_qa(
                rid,
                kind="technical",
                passed=status == "qa_passed",
                detail=qa_report or probe,
                checked_at=stamp,
            )

        return PilotResult(
            status=status,
            message=message,
            run_id=rid,
            out_dir=str(destination),
            story_package_path=str(story_path),
            narration_path=str(narration_path),
            audio_path=str(final_audio),
            video_path=str(video_path) if video_path.is_file() else "",
            contact_sheet_path=str(contact_sheet_path) if contact_sheet_path.is_file() else "",
            qa_report_path=str(qa_path) if qa_path.is_file() else "",
            report_path=str(report_path),
            detail={"probe": probe, "render": render_detail, "qa": qa_report},
        )
    except RenderError as exc:
        return PilotResult(
            status="failed",
            message=str(exc),
            run_id=rid,
            out_dir=str(destination),
            story_package_path=str(story_path) if story_path.is_file() else "",
            narration_path=str(narration_path) if narration_path.is_file() else "",
            audio_path=str(final_audio) if final_audio.is_file() else "",
            video_path=str(video_path) if video_path.is_file() else "",
        )
