"""Build the outbox directory the production server accepts."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from app.reels.config import ReelConfig
from app.reels.store import ReelStore, utc_now


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_package(config: ReelConfig, store: ReelStore, reel_id: str, *, video_path: Path, now: datetime) -> Path:
    """Copy the finished MP4 and the four sidecar files into the outbox."""

    reel = store.get(reel_id)
    if reel is None:
        raise FileNotFoundError(reel_id)
    if reel["local_status"] not in {"qa_passed", "packaged", "queued", "uploaded"}:
        raise ValueError(f"reel {reel_id} is not ready to package")
    destination = config.outbox_dir / reel_id
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "reel.mp4"
    if Path(video_path).resolve() != target.resolve():
        shutil.copy2(video_path, target)
    checksum = file_sha256(target)
    caption = reel["caption_fa"] or ""
    (destination / "caption.txt").write_text(caption, encoding="utf-8")
    sources = [
        {
            "url": row["url"],
            "publisher": row["publisher"],
            "title": row["title"],
            "verified_at": row["verified_at"],
            "excerpt": row["excerpt"],
        }
        for row in store.sources_for(reel_id)
    ]
    attribution = [
        {
            "path": row["path"],
            "source_url": row["source_url"],
            "author": row["author"],
            "license": row["license_name"],
            "license_url": row["license_url"],
            "role": row["role"],
        }
        for row in store.assets_for(reel_id)
    ]
    qa = [
        {"kind": row["kind"], "passed": bool(row["passed"]), "detail": json.loads(row["detail_json"] or "{}")}
        for row in store.qa_for(reel_id)
    ]
    scheduled = reel["scheduled_for"]
    if not scheduled:
        local = now.astimezone(config.zone)
        scheduled_dt = local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        scheduled = scheduled_dt.isoformat()
    manifest = {
        "reel_id": reel_id,
        "story_fingerprint": reel["story_fingerprint"],
        "target_page": "almanyar",
        "title": reel["title"],
        "category": reel["category"],
        "affected_audience": reel["affected_audience"],
        "editorial_angle": reel["editorial_angle"],
        "checksum_sha256": checksum,
        "duration_seconds": reel["duration_seconds"],
        "width": reel["width"],
        "height": reel["height"],
        "facts_checked_at": reel["facts_checked_at"],
        "generated_at": reel["generation_finished_at"],
        "scheduled_for": scheduled,
        "qa": qa,
        "qa_passed": all(item["passed"] for item in qa) if qa else False,
        "cost_usd": _cost_total(store, reel_id),
        "human_publish_approved": False,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "sources.json").write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
    (destination / "attribution.json").write_text(json.dumps(attribution, ensure_ascii=False, indent=2), encoding="utf-8")
    with store.connect() as connection:
        connection.execute(
            """
            UPDATE reels
            SET checksum_sha256 = ?, video_path = ?, scheduled_for = ?, local_status = 'queued', updated_at = ?
            WHERE reel_id = ?
            """,
            (checksum, str(target), scheduled, utc_now(now), reel_id),
        )
    return destination


def _cost_total(store: ReelStore, reel_id: str) -> float:
    with store.connect() as connection:
        row = connection.execute(
            "SELECT COALESCE(SUM(usd), 0) AS total FROM reel_costs WHERE reel_id = ?",
            (reel_id,),
        ).fetchone()
    return float(row["total"])
