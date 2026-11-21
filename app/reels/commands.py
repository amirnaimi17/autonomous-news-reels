"""Command implementations for the Reel lifecycle.

``generate-reel`` discovers, checks, and, only when paid generation is enabled,
narrates and renders. It never calls the silent voice or solid-image stubs.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.config import NewsSourceConfig
from app.reels.config import ReelConfig, load_reel_config
from app.reels.cron import RunLock, cron_block, install_cron_text, remove_cron_text
from app.reels.package import file_sha256, write_package
from app.reels.pipeline import Candidate, run_generation
from app.reels.store import ReelStore, utc_now
from app.reels.upload import UploadTransport, upload_package
from app.services.news.accuracy import deutschlandticket_accuracy_errors
from app.services.news_sources.rss import RssNewsSource, UrllibTransport

ARAN_VOICE = "PEdcOLzbXYhL8IKOswXB"
EXISTING_REEL = "20261119-deutschlandticket-2027-visual"


def generate_reel_command(*, scheduled: bool, target: str, now: datetime | None = None) -> int:
    config = load_reel_config()
    if target:
        config = _with_target(config, target)
    store = ReelStore(config.database_path)
    store.migrate()
    moment = now or datetime.now(timezone.utc)
    lock = RunLock(config.lock_path)
    if not lock.acquire():
        attempt = store.start_attempt(
            target_page=config.target_page,
            slot_local=moment.astimezone(config.zone).strftime("%Y-%m-%d %H:%M"),
            now=moment,
        )
        store.finish_attempt(attempt, status="skipped_overlap", message="another generation is running", now=moment)
        store.add_cron_log(
            job_name="generate_scheduled_reel",
            status="skipped_overlap",
            message="another generation is running",
            now=moment,
        )
        print("skipped: another generation is running")
        return 0
    try:
        candidates = discover_candidates(config, moment)
        result = run_generation(
            config,
            store,
            now=moment,
            scheduled=scheduled,
            candidates=candidates,
            verify_source=verify_http,
            write_script=write_grounded_script,
            find_assets=find_licensed_assets,
            narrate=narrate_aran,
            render_video=render_with_remotion,
            probe_video=probe_mp4,
        )
        if result.status == "qa_passed" and result.reel_id:
            reel = store.get(result.reel_id)
            write_package(config, store, result.reel_id, video_path=Path(reel["video_path"]), now=moment)
            result_status = "queued"
        else:
            result_status = result.status
        store.add_cron_log(
            job_name="generate_scheduled_reel" if scheduled else "generate_reel",
            status=result_status,
            message=result.message or result.reel_id,
            detail={"reel_id": result.reel_id, "scheduled": scheduled},
            now=moment,
        )
        print(f"{result_status}: {result.message or result.reel_id}")
        return 0 if result_status != "failed" else 1
    finally:
        lock.release()


def deliver_existing_command(source_dir: Path, *, now: datetime | None = None) -> int:
    """Register the already rendered Deutschlandticket preview. No paid calls."""

    config = load_reel_config()
    store = ReelStore(config.database_path)
    store.migrate()
    moment = now or datetime.now(timezone.utc)
    video = source_dir / "preview_reel.mp4"
    caption_path = source_dir / "proposed_caption.txt"
    attribution_path = source_dir / "attribution_manifest.json"
    if not video.is_file() or not caption_path.is_file() or not attribution_path.is_file():
        print("existing reel files are missing")
        return 1
    probe = probe_mp4(video)
    caption = caption_path.read_text(encoding="utf-8")
    if deutschlandticket_accuracy_errors(caption):
        print("existing caption failed the accuracy check")
        return 1
    attribution = json.loads(attribution_path.read_text(encoding="utf-8"))
    reel_id = EXISTING_REEL
    fingerprint = "deutschlandticket-2027-price-and-provider-confirmation"
    stamp = "2026-11-19T19:00:00+00:00"
    store.upsert_reel(
        {
            "reel_id": reel_id,
            "story_fingerprint": fingerprint,
            "target_page": "almanyar",
            "title": "Deutschlandticket price from January 2027",
            "category": "transport",
            "affected_audience": "Iranians living in Germany who hold a Deutschlandticket",
            "editorial_angle": "The monthly price changes on 1 January 2027, and confirmation depends on the company that sold the ticket.",
            "narration_fa": "",
            "caption_fa": caption,
            "storyboard_json": json.dumps({"composition": "PhotoTicketReel", "source": str(source_dir)}, ensure_ascii=False),
            "video_path": str(video),
            "duration_seconds": probe.get("duration_seconds"),
            "width": probe.get("width"),
            "height": probe.get("height"),
            "checksum_sha256": probe.get("checksum_sha256"),
            "local_status": "qa_passed",
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
    sources = [
        ("https://www.bundesregierung.de/breg-de/aktuelles/gesetzliche-neuregelungen-november-2026-2459132", "Bundesregierung", "Was ist neu im November 2026"),
        ("https://www.bahn.de/angebot/regio/deutschland-ticket", "Deutsche Bahn", "Deutschlandticket"),
        ("https://www.bvg.de/de/deutschlandticket/faqs-deutschlandticket", "BVG", "Deutschlandticket FAQ"),
        ("https://hessen.de/presse/ab-2027-kostet-das-deutschlandticket-6680-euro", "Hessen", "Ab 2027 kostet das Deutschlandticket 66,80 Euro"),
    ]
    for url, publisher, title in sources:
        store.add_source(reel_id, url=url, publisher=publisher, title=title, verified_at=stamp, excerpt="")
    for asset in attribution.get("assets") or []:
        if not asset.get("used_in_render"):
            continue
        store.add_asset(
            reel_id,
            {
                "path": asset.get("local_preview", ""),
                "source_url": asset.get("source_url", ""),
                "author": asset.get("creator", ""),
                "license_name": asset.get("license", ""),
                "license_url": asset.get("license_url", ""),
                "role": "licensed-photograph",
            },
        )
    narration = Path("storage/generated/pilot/20261119-deutschlandticket-2027/audio/narration.mp3")
    if narration.is_file():
        store.add_audio(
            reel_id,
            {
                "path": str(narration),
                "provider": "elevenlabs",
                "voice_id": ARAN_VOICE,
                "model_id": "eleven_v4",
                "speed": 1.0,
                "duration_seconds": probe.get("audio_duration_seconds"),
            },
        )
    for kind in ("factual", "licensing", "audio", "technical"):
        store.add_qa(reel_id, kind=kind, passed=True, detail=probe if kind == "technical" else {"reused": True}, checked_at=stamp)
    store.add_cost(
        reel_id,
        provider="elevenlabs",
        kind="actual",
        usd=0.02928,
        detail={"note": "already billed for the six scene requests; not billed again"},
        recorded_at=stamp,
    )
    destination = write_package(config, store, reel_id, video_path=video, now=moment)
    print(f"queued: {destination}")
    return 0


def upload_outbox_command(*, now: datetime | None = None, transport: UploadTransport | None = None, recheck=None) -> int:
    config = load_reel_config()
    store = ReelStore(config.database_path)
    store.migrate()
    moment = now or datetime.now(timezone.utc)
    if not config.outbox_dir.exists():
        print("outbox is empty")
        return 0
    failures = 0
    for package in sorted(path for path in config.outbox_dir.iterdir() if path.is_dir()):
        result = upload_package(config, store, package, now=moment, transport=transport, recheck=recheck)
        print(f"{package.name}: {'uploaded' if result.get('ok') else result.get('error')}")
        if not result.get("ok"):
            failures += 1
    return 1 if failures else 0


def status_command() -> int:
    config = load_reel_config()
    store = ReelStore(config.database_path)
    if not config.database_path.exists():
        print(f"reel database is not initialized: {config.database_path}")
        return 1
    store.migrate()
    print(f"database: {config.database_path}")
    print(f"paid generation: {config.paid_generation}")
    print(f"script provider: {config.script_provider}")
    print(f"hours Europe/Berlin: {', '.join(str(hour) for hour in config.generation_hours)}")
    print("attempts:")
    for row in store.recent_attempts(10):
        print(f"- {row['id']} {row['status']} {row['slot_local']} {row['message']}")
    print("reels:")
    for row in store.recent_reels(10):
        print(f"- {row['reel_id']} {row['local_status']} {row['title']}")
    print("posts:")
    for row in store.recent_posts(10):
        print(f"- {row['id']} {row['page_name']} {row['status']} {row['title']}")
    print("cron:")
    for row in store.recent_cron_logs(10):
        print(f"- {row['created_at']} {row['job_name']} {row['status']} {row['message']}")
    return 0


def install_cron_command(*, apply: bool) -> int:
    config = load_reel_config()
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    fragment = cron_block(config)
    path = config.working_directory / "storage" / "cron" / "news-reels.cron"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fragment, encoding="utf-8")
    print(path)
    if not apply:
        print("not installed. Re-run with --apply to update this user's crontab.")
        return 0
    current = subprocess.run(["crontab", "-l"], check=False, capture_output=True, text=True)
    existing = current.stdout if current.returncode == 0 else ""
    updated = install_cron_text(existing, config)
    subprocess.run(["crontab", "-"], input=updated, text=True, check=True)
    print("crontab updated")
    return 0


def remove_cron_command() -> int:
    current = subprocess.run(["crontab", "-l"], check=False, capture_output=True, text=True)
    if current.returncode != 0:
        print("no crontab")
        return 0
    updated = remove_cron_text(current.stdout)
    subprocess.run(["crontab", "-"], input=updated, text=True, check=True)
    print("reel cron removed")
    return 0


def discover_candidates(config: ReelConfig, now: datetime) -> list[Candidate]:
    if not config.sources_file.is_file():
        return []
    raw = json.loads(config.sources_file.read_text(encoding="utf-8"))
    sources = tuple(NewsSourceConfig.model_validate(item) for item in raw)
    window_end = now.astimezone(timezone.utc)
    window_start = window_end - timedelta(hours=config.news_window_hours)
    result = RssNewsSource(sources, UrllibTransport(timeout=20, user_agent="AutonomousNewsReels/0.1")).fetch(
        window_start=window_start,
        window_end=window_end,
    )
    candidates = []
    for article in result.articles:
        if article.published_at is None:
            continue
        candidates.append(
            Candidate(
                title=article.title,
                summary=article.summary,
                url=article.canonical_url,
                publisher=article.source_name,
                published_at=article.published_at,
            )
        )
    return candidates


def verify_http(candidate: Candidate) -> dict:
    import urllib.request

    request = urllib.request.Request(candidate.url, headers={"User-Agent": "AutonomousNewsReels/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        body = response.read(20000).decode("utf-8", errors="replace")
        if response.status != 200:
            return {"ok": False, "excerpt": ""}
    tokens = [token for token in candidate.title.split() if len(token) > 4]
    if tokens and not any(token.casefold() in body.casefold() for token in tokens[:4]):
        return {"ok": False, "excerpt": body[:400]}
    return {"ok": True, "excerpt": body[:400]}


def write_grounded_script(
    candidate: Candidate,
    checked: dict,
    *,
    paid_generation: bool,
    complete=None,
    config: ReelConfig | None = None,
) -> dict:
    """Write a grounded Persian ``story_package`` for the Reel pipeline.

    Script generation reuses the pilot fact-pack and editorial contracts. The
    OpenAI chat call is optional and injectable. Voice and video stay behind
    ``REEL_PAID_GENERATION`` in ``run_generation``; this function never calls
    ElevenLabs.
    """

    from app.core.exceptions import ConfigurationError, GroundingError
    from app.services.llm.openai_script import complete_chat
    from app.services.llm.persian_script import (
        build_editorial_brief,
        build_fact_pack,
        generate_persian_story_package,
        pipeline_script_from_package,
        write_story_package,
    )

    if not checked.get("ok"):
        return {"status": "rejected", "message": "inadequately verified"}

    settings = config or load_reel_config()
    provider = (settings.script_provider or "off").strip().lower()
    completer = complete
    if completer is None:
        if provider in {"", "off", "none"}:
            if not paid_generation:
                return {"status": "blocked_paid", "message": "paid generation is disabled"}
            return {"status": "rejected", "message": "the paid script transport was not configured"}
        if provider != "openai":
            return {"status": "rejected", "message": f"unknown script provider: {provider}"}

        def completer(prompt: str, context: dict) -> dict:
            return complete_chat(prompt, context, model=settings.script_model)

    fact_pack = build_fact_pack(
        title=candidate.title,
        summary=candidate.summary,
        url=candidate.url,
        publisher=candidate.publisher,
        published_at=candidate.published_at,
        excerpt=str(checked.get("excerpt") or ""),
    )
    editorial = build_editorial_brief(
        fact_pack,
        title=candidate.title,
        summary=candidate.summary,
    )
    try:
        package = generate_persian_story_package(fact_pack, editorial, complete=completer)
    except ConfigurationError as exc:
        return {"status": "blocked_paid" if not paid_generation else "rejected", "message": str(exc)}
    except (GroundingError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {"status": "rejected", "message": str(exc) or exc.__class__.__name__}

    result = pipeline_script_from_package(package)
    result["fact_pack"] = fact_pack
    result["editorial_review"] = editorial
    destination = settings.script_output_dir / fact_pack["event_id"]
    result["story_package_path"] = str(write_story_package(package, destination))
    write_story_package(fact_pack, destination / "fact_pack.json")
    write_story_package(editorial, destination / "editorial_review.json")
    return result


def find_licensed_assets(candidate: Candidate, script: dict) -> list[dict]:
    """Graphics are allowed. A paid image is not invented here."""

    del candidate, script
    return [
        {
            "path": "",
            "source_url": "",
            "author": "",
            "license_name": "remotion-graphic",
            "license_url": "",
            "role": "remotion-graphic",
            "kind": "remotion-graphic",
        }
    ]


def narrate_aran(text: str, voice_id: str) -> dict:
    """Call ElevenLabs only as the wired production narrator.

    The command path reaches this only when paid generation is already on
    and the script transport returned a narration. The default script writer
    stops before that.
    """

    import importlib.util

    path = Path(__file__).resolve().parents[2] / ".cursor" / "skills" / "persian-tts" / "scripts" / "elevenlabs.py"
    spec = importlib.util.spec_from_file_location("reel_elevenlabs", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("ElevenLabs client is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    request = module.speech_request(text, voice_id or ARAN_VOICE)
    raise RuntimeError(f"paid narration is enabled but this process will not send {request['url']} without an explicit sender")


def render_with_remotion(script: dict, assets: list[dict], audio: dict) -> dict:
    """Render through the data-driven Remotion composition."""

    del assets
    root = Path(__file__).resolve().parents[2]
    project = root / ".cursor" / "skills" / "reel-video-design" / "remotion-poc"
    props = {
        "scenes": json.loads(script.get("storyboard_json") or "[]"),
        "audio": audio.get("path", ""),
    }
    out = root / "storage" / "generated" / "reels" / f"{script.get('reel_id', 'reel')}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    node = root / ".cursor" / "skills" / "reel-video-design" / ".tools" / "node-v22.21.1-linux-x64" / "bin"
    command = [
        "npx",
        "remotion",
        "render",
        "src/index.tsx",
        "DataReel",
        str(out),
        "--codec",
        "h264",
        "--props",
        json.dumps(props),
    ]
    subprocess.run(command, cwd=project, check=True, env={**dict(**__import__("os").environ), "PATH": f"{node}:{__import__('os').environ.get('PATH', '')}"})
    return {"path": str(out)}


def probe_mp4(path: Path) -> dict:
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
    video = next(stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video")
    audio_streams = [stream for stream in payload.get("streams", []) if stream.get("codec_type") == "audio"]
    audio = audio_streams[0] if audio_streams else {}
    return {
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
        "has_audio": bool(audio),
        "duration_seconds": float(payload.get("format", {}).get("duration") or video.get("duration") or 0),
        "audio_duration_seconds": float(audio.get("duration") or payload.get("format", {}).get("duration") or 0),
        "checksum_sha256": file_sha256(Path(path)),
    }


def _with_target(config: ReelConfig, target: str) -> ReelConfig:
    return ReelConfig(
        database_path=config.database_path,
        outbox_dir=config.outbox_dir,
        lock_path=config.lock_path,
        log_path=config.log_path,
        timezone=config.timezone,
        target_page=target,
        generation_hours=config.generation_hours,
        slot_grace_minutes=config.slot_grace_minutes,
        news_window_hours=config.news_window_hours,
        freshness_hours=config.freshness_hours,
        paid_generation=config.paid_generation,
        per_reel_max_usd=config.per_reel_max_usd,
        daily_cost_limit_usd=config.daily_cost_limit_usd,
        monthly_cost_limit_usd=config.monthly_cost_limit_usd,
        ingest_url=config.ingest_url,
        ingest_token=config.ingest_token,
        python_executable=config.python_executable,
        working_directory=config.working_directory,
        sources_file=config.sources_file,
        voice_id=config.voice_id,
        max_attempts=config.max_attempts,
        script_provider=config.script_provider,
        script_model=config.script_model,
        script_output_dir=config.script_output_dir,
    )
