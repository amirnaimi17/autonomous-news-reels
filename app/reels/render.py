"""Remotion DataReel rendering for Persian Instagram Reels.

Stages narration audio and scene images into the Remotion ``public/`` tree,
builds DataReel props from a Phase 3 ``story_package``, and invokes the existing
POC CLI. Does not call OpenAI or ElevenLabs.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from app.reels.package import file_sha256

FPS = 30
WIDTH = 1080
HEIGHT = 1920
ROOT = Path(__file__).resolve().parents[2]
REMOTION_PROJECT = ROOT / ".cursor" / "skills" / "reel-video-design" / "remotion-poc"
NODE_BIN = ROOT / ".cursor" / "skills" / "reel-video-design" / ".tools" / "node-v22.21.1-linux-x64" / "bin"
PUBLIC = REMOTION_PROJECT / "public"
DEFAULT_OUT_DIR = ROOT / "storage" / "generated" / "reels"

Runner = Callable[[list[str], Path, dict[str, str]], subprocess.CompletedProcess]


class RenderError(RuntimeError):
    """Remotion staging or render failed."""


def probe_media(path: Path) -> dict[str, Any]:
    """FFprobe a media file for duration and stream codecs."""

    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height,duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)
    streams = payload.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio_streams = [stream for stream in streams if stream.get("codec_type") == "audio"]
    audio = audio_streams[0] if audio_streams else {}
    duration = float(payload.get("format", {}).get("duration") or video.get("duration") or audio.get("duration") or 0)
    return {
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "has_audio": bool(audio),
        "has_video": bool(video),
        "duration_seconds": duration,
        "audio_duration_seconds": float(audio.get("duration") or duration or 0),
        "checksum_sha256": file_sha256(Path(path)) if Path(path).is_file() else "",
    }


def validate_reel_probe(probe: dict[str, Any], *, min_seconds: float = 1.0, max_seconds: float = 900.0) -> list[str]:
    """Return technical problems for a rendered vertical Reel."""

    problems: list[str] = []
    if probe.get("width") != WIDTH or probe.get("height") != HEIGHT:
        problems.append("resolution")
    codec = str(probe.get("video_codec") or "").lower()
    if codec not in {"h264", "avc1"}:
        problems.append("video codec")
    if not probe.get("has_audio"):
        problems.append("audio missing")
    audio_codec = str(probe.get("audio_codec") or "").lower()
    # Documented Remotion H.264 output muxes AAC. Do not accept other codecs.
    if probe.get("has_audio") and audio_codec != "aac":
        problems.append("audio codec")
    duration = float(probe.get("duration_seconds") or 0)
    if duration < min_seconds or duration > max_seconds:
        problems.append("duration")
    return problems


def _asset_credit(asset: dict[str, Any] | None) -> str:
    """Format author/license for a displayed photograph. Empty for graphics."""

    if not isinstance(asset, dict):
        return ""
    author = str(asset.get("author") or "").strip()
    license_name = str(asset.get("license_name") or "").strip()
    if author and license_name:
        return f"{author} / {license_name}"
    return author or license_name


def seconds_to_frames(seconds: float, *, fps: int = FPS) -> int:
    return max(1, int(round(float(seconds) * fps)))


def _short_caption(text: str, limit: int = 120) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    trimmed = cleaned[: limit - 1].rsplit(" ", 1)[0]
    return trimmed or cleaned[:limit]


def stage_file(source: Path, destination: Path) -> None:
    """Copy into Remotion public/. Symlinks are avoided — the static server 404s them."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    shutil.copy2(source, destination)


def make_graphic_png(path: Path, *, color: str = "0x0B1F3A") -> Path:
    """Create a simple full-frame PNG with ffmpeg (no paid providers)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s={WIDTH}x{HEIGHT}:d=1",
            "-frames:v",
            "1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def make_silent_mp3(path: Path, *, seconds: float = 8.0) -> Path:
    """Offline silent MP3 fixture for render tests."""

    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            f"{seconds:.3f}",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "5",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return path


def build_data_scenes(
    story: dict[str, Any],
    *,
    assets: list[dict[str, Any]] | None = None,
    audio_duration_seconds: float | None = None,
    fps: int = FPS,
) -> list[dict[str, Any]]:
    """Map a story_package (+ optional assets) onto DataReel scene props (relative paths unset).

    Assets stay index-aligned with scenes. A missing file becomes a graphic for
    that scene only; later scene images are not shifted forward.
    """

    raw_scenes = story.get("scenes") or []
    if not isinstance(raw_scenes, list) or not raw_scenes:
        raise RenderError("story package has no scenes")
    asset_list = list(assets or [])
    weights: list[float] = []
    for scene in raw_scenes:
        if not isinstance(scene, dict):
            raise RenderError("each scene must be an object")
        seconds = float(scene.get("duration_seconds") or 0)
        weights.append(seconds if seconds > 0 else 3.0)
    total_weight = sum(weights) or float(len(weights))
    target = float(audio_duration_seconds) if audio_duration_seconds and audio_duration_seconds > 0 else total_weight
    built: list[dict[str, Any]] = []
    for index, scene in enumerate(raw_scenes):
        assert isinstance(scene, dict)
        share = weights[index] / total_weight
        seconds = target * share
        headline = str(scene.get("on_screen_text") or scene.get("headline") or "").strip()
        caption = _short_caption(str(scene.get("narration") or headline))
        asset = asset_list[index] if index < len(asset_list) and isinstance(asset_list[index], dict) else None
        raw_path = str((asset or {}).get("path") or "").strip() if asset else ""
        asset_path = raw_path if raw_path and Path(raw_path).is_file() else ""
        graphic = not bool(asset_path)
        # Attribution belongs only to a displayed photograph, never a shifted neighbor.
        credit = "" if graphic else _asset_credit(asset)
        built.append(
            {
                "durationFrames": seconds_to_frames(seconds, fps=fps),
                "headline": headline or f"صحنه {index + 1}",
                "caption": caption or headline or f"صحنه {index + 1}",
                "source_image": asset_path,
                "credit": credit,
                "graphic": graphic,
                "number": int(scene.get("number") or index + 1),
            }
        )
    return built


def stage_render_bundle(
    story: dict[str, Any],
    audio_path: Path,
    *,
    assets: list[dict[str, Any]] | None = None,
    render_id: str | None = None,
    audio_duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Copy/symlink media into public/runtime/<id>/ and return Remotion props."""

    if not audio_path.is_file():
        raise RenderError(f"audio file is missing: {audio_path}")
    rid = render_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    stage_rel = Path("runtime") / rid
    stage_dir = PUBLIC / stage_rel
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)

    audio_name = "narration.mp3"
    stage_file(audio_path, stage_dir / audio_name)
    scenes = build_data_scenes(story, assets=assets, audio_duration_seconds=audio_duration_seconds)
    remotion_scenes: list[dict[str, Any]] = []
    for index, scene in enumerate(scenes):
        image_rel = None
        source = scene.get("source_image") or ""
        if source and Path(source).is_file():
            ext = Path(source).suffix.lower() or ".jpg"
            image_name = f"scene-{index + 1:02d}{ext}"
            stage_file(Path(source), stage_dir / image_name)
            image_rel = str(stage_rel / image_name).replace("\\", "/")
            graphic = False
        else:
            image_name = f"scene-{index + 1:02d}-graphic.png"
            make_graphic_png(stage_dir / image_name)
            image_rel = str(stage_rel / image_name).replace("\\", "/")
            graphic = True
        remotion_scenes.append(
            {
                "durationFrames": scene["durationFrames"],
                "headline": scene["headline"],
                "caption": scene["caption"],
                "image": image_rel,
                "credit": scene.get("credit") or "",
                "graphic": graphic,
            }
        )
    props = {
        "scenes": remotion_scenes,
        "audioFile": str(stage_rel / audio_name).replace("\\", "/"),
    }
    return {"render_id": rid, "stage_dir": stage_dir, "props": props, "props_path": stage_dir / "props.json"}


def _default_runner(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, check=True, env=env, capture_output=True, text=True)


def remotion_command(props_path: Path, out_path: Path) -> list[str]:
    return [
        "npx",
        "remotion",
        "render",
        "src/index.tsx",
        "DataReel",
        str(out_path),
        "--codec",
        "h264",
        "--props",
        str(props_path),
    ]


def render_data_reel(
    story: dict[str, Any],
    audio_path: Path,
    *,
    out_path: Path,
    assets: list[dict[str, Any]] | None = None,
    overwrite: bool = False,
    runner: Runner | None = None,
    render_id: str | None = None,
) -> dict[str, Any]:
    """Stage inputs, render DataReel, and validate the MP4 with ffprobe."""

    out_path = Path(out_path).resolve()
    if out_path.exists() and not overwrite:
        raise RenderError(f"refusing to overwrite existing video: {out_path}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    audio_probe = probe_media(audio_path)
    bundle = stage_render_bundle(
        story,
        Path(audio_path),
        assets=assets,
        render_id=render_id,
        audio_duration_seconds=audio_probe.get("duration_seconds"),
    )
    props_path = Path(bundle["props_path"]).resolve()
    props_path.write_text(json.dumps(bundle["props"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    env = {**dict(**__import__("os").environ), "PATH": f"{NODE_BIN}:{__import__('os').environ.get('PATH', '')}"}
    command = remotion_command(props_path, out_path)
    execute = runner or _default_runner
    try:
        execute(command, REMOTION_PROJECT, env)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc))[-2000:]
        raise RenderError(f"Remotion render failed: {detail}") from exc
    if not out_path.is_file():
        raise RenderError(f"Remotion did not write {out_path}")
    probe = probe_media(out_path)
    problems = validate_reel_probe(probe)
    return {
        "path": str(out_path),
        "probe": probe,
        "problems": problems,
        "render_id": bundle["render_id"],
        "props": bundle["props"],
        "ok": not problems,
    }


def story_from_script(script: dict[str, Any]) -> dict[str, Any]:
    """Recover a story_package-like object from pipeline script dicts."""

    if isinstance(script.get("story_package"), dict):
        return script["story_package"]
    board = script.get("storyboard_json") or "[]"
    if isinstance(board, str):
        try:
            scenes = json.loads(board)
        except json.JSONDecodeError as exc:
            raise RenderError("storyboard_json is not valid JSON") from exc
    else:
        scenes = board
    if isinstance(scenes, dict) and "scenes" in scenes:
        return scenes
    if not isinstance(scenes, list):
        raise RenderError("storyboard_json must be a scene list or story package")
    return {
        "schema_version": "pilot-1",
        "event_id": str(script.get("reel_id") or "pipeline-reel"),
        "language": "fa-IR",
        "audience": "Iranians living in Germany",
        "headline": str(script.get("angle") or script.get("caption") or "خبر"),
        "source_urls": ["https://example.invalid/pipeline"],
        "claims": [{"text": "pipeline storyboard", "source_urls": ["https://example.invalid/pipeline"]}],
        "duration_seconds": sum(float(scene.get("duration_seconds") or 0) for scene in scenes if isinstance(scene, dict)),
        "scenes": scenes,
        "disclaimers": [],
    }
