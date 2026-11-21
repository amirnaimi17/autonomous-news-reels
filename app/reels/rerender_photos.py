"""Re-render an existing live pilot with real photographs (no paid TTS/OpenAI)."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.reels.photos import (
    PhotoError,
    assets_for_render,
    build_scene_photo_queries,
    collect_scene_photos,
    relevance_terms_from_queries,
    require_photographic_assets,
    write_attribution_manifest,
)
from app.reels.pilot import run_persian_reel_pilot
from app.reels.qa import technical_qa_report, write_contact_sheet
from app.reels.render import build_data_scenes, probe_media


def rerender_with_photos(
    *,
    source_dir: Path,
    out_dir: Path,
    scene_queries: list[list[str]] | None = None,
    require_photos: bool = True,
) -> dict[str, Any]:
    """Copy story + Aran audio from ``source_dir`` and re-render with new photos."""

    source = Path(source_dir)
    destination = Path(out_dir)
    if destination.resolve() == source.resolve():
        raise PhotoError("refusing to overwrite the source pilot directory")
    story_path = source / "story_package.json"
    audio_path = source / "audio" / "narration.mp3"
    narration_path = source / "narration.txt"
    if not story_path.is_file():
        raise PhotoError(f"missing story package: {story_path}")
    if not audio_path.is_file():
        raise PhotoError(f"missing narration mp3: {audio_path}")
    story = json.loads(story_path.read_text(encoding="utf-8"))
    destination.mkdir(parents=True, exist_ok=True)

    # Preserve originals by copying inputs; never rewrite source reel.mp4.
    shutil.copy2(story_path, destination / "story_package.json")
    if narration_path.is_file():
        shutil.copy2(narration_path, destination / "narration.txt")
    for name in ("fact_pack.json", "editorial_review.json"):
        if (source / name).is_file():
            shutil.copy2(source / name, destination / name)
    if (source / "audio" / "voice_manifest.json").is_file():
        audio_dir = destination / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "audio" / "voice_manifest.json", audio_dir / "voice_manifest.json")

    if scene_queries is None:
        headline = str(story.get("headline") or story.get("event_id") or "Germany news")
        summary = " ".join(str(claim.get("text") or "") for claim in (story.get("claims") or []) if isinstance(claim, dict))
        scene_queries = build_scene_photo_queries(
            headline,
            summary,
            {"story_package": story},
        )
    relevance = [relevance_terms_from_queries(group) for group in scene_queries]
    photos, search_log = collect_scene_photos(
        scene_queries,
        destination / "assets",
        relevance_terms=relevance,
    )
    search_log.write(destination / "image_search_log.json")
    write_attribution_manifest(photos, destination / "attribution_manifest.json", reel_id=destination.name)
    assets = assets_for_render(photos)
    (destination / "assets.json").write_text(json.dumps(assets, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    problems = require_photographic_assets(assets, expected_scenes=len(scene_queries))
    if require_photos and problems:
        raise PhotoError("photographic acceptance gate failed: " + "; ".join(problems))

    # Pre-render mapping check: every scene must be a photograph, not a graphic.
    audio_duration = probe_media(audio_path).get("duration_seconds")
    scenes = build_data_scenes(story, assets=assets, audio_duration_seconds=audio_duration)
    graphic_flags = [bool(scene.get("graphic")) for scene in scenes]
    if require_photos and any(graphic_flags):
        raise PhotoError(f"scene graphic flags must all be false before render: {graphic_flags}")

    result = run_persian_reel_pilot(
        out_dir=destination,
        run_id=destination.name,
        story_package=story,
        audio_path=audio_path,
        assets=assets,
        require_live_voice=False,  # existing Aran MP3 path supplied; no TTS
        overwrite=True,
        database_path=destination / "pilot.sqlite3",
    )
    if result.status != "qa_passed":
        raise PhotoError(f"re-render QA failed: {result.status} {result.message}")

    # Post-render: confirm Remotion staged photographs (not only graphic plates).
    props_candidates = list(
        (Path(".cursor") / "skills" / "reel-video-design" / "remotion-poc" / "public" / "runtime" / destination.name).glob("props.json")
    )
    staged_photos = 0
    if props_candidates:
        props = json.loads(props_candidates[0].read_text(encoding="utf-8"))
        for scene in props.get("scenes") or []:
            if scene.get("graphic") is False and scene.get("image"):
                staged_photos += 1
    if require_photos and staged_photos < 4:
        raise PhotoError(f"Remotion staged only {staged_photos}/4 photographs")

    # Refresh QA with audible check against reused Aran audio.
    qa = technical_qa_report(
        Path(result.video_path),
        contact_sheet=destination / "contact-sheet.jpg",
        narration=(destination / "narration.txt").read_text(encoding="utf-8") if (destination / "narration.txt").is_file() else "",
        require_audible_audio=True,
    )
    (destination / "qa_technical.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not qa.get("technical_pass"):
        raise PhotoError("post-render technical QA failed: " + "; ".join(qa.get("problems") or []))

    report = {
        "status": "qa_passed",
        "source_dir": str(source.resolve()),
        "out_dir": str(destination.resolve()),
        "video": result.video_path,
        "contact_sheet": str(destination / "contact-sheet.jpg"),
        "audio_reused": str(Path(result.audio_path).resolve() if result.audio_path else audio_path.resolve()),
        "openai_calls": 0,
        "elevenlabs_calls": 0,
        "photos": [asset.__dict__ for asset in photos],
        "graphic_flags_pre_render": graphic_flags,
        "staged_photographs": staged_photos,
        "qa": qa,
        "cron_enabled": False,
        "instagram_publish_enabled": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (destination / "photo_rerender_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
