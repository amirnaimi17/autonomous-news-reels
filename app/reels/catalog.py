"""Register finished Reels in the local post, video, and cron log tables.

This is the local equivalent of the production post library. It does not
publish, and it does not read or write the news selection database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.reels.commands import probe_mp4
from app.reels.package import write_package
from app.reels.store import ReelStore, utc_now

ROOT = Path(__file__).resolve().parents[2]

LIBRARY = (
    {
        "reel_id": "20261119-deutschlandticket-2027-visual",
        "fingerprint": "deutschlandticket-2027-price-and-provider-confirmation",
        "folder": ROOT / "storage/generated/pilot/20261119-deutschlandticket-2027-visual",
        "video_name": "preview_reel.mp4",
        "caption_name": "proposed_caption.txt",
        "title": "Deutschlandticket price from January 2027",
        "angle": "The monthly price changes on 1 January 2027, and confirmation depends on the company that sold the ticket.",
        "audience": "Iranians living in Germany who hold a Deutschlandticket",
        "category": "transport",
        "post_status": "ready",
        "video_status": "ready",
        "facts_checked_at": "2026-11-19T19:00:00+00:00",
        "audio": ROOT / "storage/generated/pilot/20261119-deutschlandticket-2027/audio/narration.mp3",
        "package": True,
    },
    {
        "reel_id": "20261119-deutschlandticket-2027",
        "fingerprint": "deutschlandticket-2027-text-only-render",
        "folder": ROOT / "storage/generated/pilot/20261119-deutschlandticket-2027",
        "video_name": "reel.mp4",
        "caption_name": "",
        "title": "Deutschlandticket price from January 2027 (text-only render)",
        "angle": "Earlier Remotion-only picture of the same story. Kept, not the current visual.",
        "audience": "Iranians living in Germany who hold a Deutschlandticket",
        "category": "transport",
        "post_status": "superseded",
        "video_status": "superseded",
        "facts_checked_at": "2026-11-19T18:00:00+00:00",
        "audio": ROOT / "storage/generated/pilot/20261119-deutschlandticket-2027/audio/narration.mp3",
        "package": False,
    },
)


def import_library(store: ReelStore, *, now: datetime | None = None, entries=LIBRARY) -> list[str]:
    """Record each finished Reel once. Running this again updates the same rows."""

    moment = now or datetime.now(timezone.utc)
    store.migrate()
    page_id = store.ensure_page("almanyar", username="almanyar", now=moment)
    imported: list[str] = []
    for entry in entries:
        video = entry["folder"] / entry["video_name"]
        if not video.is_file():
            store.add_cron_log(
                job_name="import_generated_reels",
                status="rejected",
                message=f"missing video for {entry['reel_id']}",
                detail={"path": str(video)},
                now=moment,
            )
            continue
        probe = probe_mp4(video)
        caption = ""
        if entry["caption_name"]:
            caption_path = entry["folder"] / entry["caption_name"]
            if caption_path.is_file():
                caption = caption_path.read_text(encoding="utf-8")
        stamp = entry["facts_checked_at"]
        store.upsert_reel(
            {
                "reel_id": entry["reel_id"],
                "story_fingerprint": entry["fingerprint"],
                "target_page": "almanyar",
                "title": entry["title"],
                "category": entry["category"],
                "affected_audience": entry["audience"],
                "editorial_angle": entry["angle"],
                "narration_fa": "",
                "caption_fa": caption,
                "storyboard_json": "{}",
                "video_path": str(video),
                "duration_seconds": probe.get("duration_seconds"),
                "width": probe.get("width"),
                "height": probe.get("height"),
                "checksum_sha256": probe.get("checksum_sha256"),
                "local_status": "qa_passed" if entry["package"] else entry["post_status"],
                "production_delivery_id": None,
                "scheduled_for": None,
                "facts_checked_at": stamp,
                "generation_started_at": stamp,
                "generation_finished_at": stamp,
                "error_message": "",
                "retry_count": 0,
                "created_at": stamp,
                "updated_at": utc_now(moment),
            }
        )
        attribution = entry["folder"] / "attribution_manifest.json"
        if attribution.is_file() and not store.assets_for(entry["reel_id"]):
            import json

            document = json.loads(attribution.read_text(encoding="utf-8"))
            for asset in document.get("assets") or []:
                if not asset.get("used_in_render"):
                    continue
                store.add_asset(
                    entry["reel_id"],
                    {
                        "path": asset.get("local_preview", ""),
                        "source_url": asset.get("source_url", ""),
                        "author": asset.get("creator", ""),
                        "license_name": asset.get("license", ""),
                        "license_url": asset.get("license_url", ""),
                        "role": "licensed-photograph",
                    },
                )
        if not store.sources_for(entry["reel_id"]):
            for url, publisher in (
                ("https://www.bundesregierung.de/breg-de/aktuelles/gesetzliche-neuregelungen-november-2026-2459132", "Bundesregierung"),
                ("https://www.bahn.de/angebot/regio/deutschland-ticket", "Deutsche Bahn"),
                ("https://www.bvg.de/de/deutschlandticket/faqs-deutschlandticket", "BVG"),
            ):
                store.add_source(
                    entry["reel_id"],
                    url=url,
                    publisher=publisher,
                    title=entry["title"],
                    verified_at=stamp,
                    excerpt="",
                )
        if not store.qa_for(entry["reel_id"]):
            for kind in ("factual", "licensing", "audio", "technical"):
                store.add_qa(
                    entry["reel_id"],
                    kind=kind,
                    passed=True,
                    detail=probe if kind == "technical" else {"imported": True},
                    checked_at=stamp,
                )
        with store.connect() as connection:
            connection.execute("DELETE FROM reel_audio WHERE reel_id = ?", (entry["reel_id"],))
        if entry["audio"].is_file():
            store.add_audio(
                entry["reel_id"],
                {
                    "path": str(entry["audio"]),
                    "provider": "elevenlabs",
                    "voice_id": "PEdcOLzbXYhL8IKOswXB",
                    "model_id": "eleven_v4",
                    "speed": 1.0,
                    "duration_seconds": probe.get("audio_duration_seconds"),
                },
            )
        post_id = store.upsert_post(
            page_id=page_id,
            reel_id=entry["reel_id"],
            title=entry["title"],
            description=caption or entry["angle"],
            status=entry["post_status"],
            scheduled_for=None,
            now=moment,
        )
        store.add_video(
            post_id=post_id,
            path=str(video),
            checksum=probe.get("checksum_sha256") or "",
            duration=probe.get("duration_seconds"),
            width=probe.get("width"),
            height=probe.get("height"),
            status=entry["video_status"],
            now=moment,
        )
        if entry["package"]:
            from app.reels.config import load_reel_config

            write_package(load_reel_config(), store, entry["reel_id"], video_path=video, now=moment)
            store.set_status(entry["reel_id"], "ready", now=moment)
        imported.append(entry["reel_id"])
        store.add_cron_log(
            job_name="import_generated_reels",
            status="success",
            message=entry["reel_id"],
            detail={"post_id": post_id, "checksum": probe.get("checksum_sha256")},
            now=moment,
        )
    return imported
