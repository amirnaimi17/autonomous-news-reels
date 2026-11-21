"""Command line entry points for the standalone application."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from pydantic import ValidationError

from app import __version__
from app.api.routes import health_payload
from app.core.config import Settings, get_settings
from app.database.models import StatusSnapshot
from app.core.exceptions import NewsReelsError
from app.core.logging import configure_logging
from app.core.paths import ensure_media_dirs
from app.core.time import production_date
from app.database.repository import NewsReelsRepository
from app.services.factory import ensure_publish_disabled
from app.services.video.ffmpeg import FFmpegCapabilities, probe_ffmpeg, select_encoder


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news-reels", description="Autonomous news reel generator")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="Create the database, the default client, and media directories")
    sub.add_parser("status", help="Show configuration, database counts, and FFmpeg encoders")
    sub.add_parser("discover", help="Collect configured feeds and fill today's remaining selections")
    reel = sub.add_parser("init-reel-db", help="Create the Reel lifecycle database")
    del reel
    sub.add_parser("reel-status", help="Show Reel attempts and delivery state")
    generate = sub.add_parser("generate-reel", help="Research and, when paid generation is enabled, render one Reel")
    generate.add_argument("--target", default="almanyar")
    generate.add_argument("--scheduled", action="store_true")
    deliver = sub.add_parser("deliver-existing", help="Package the already rendered Deutschlandticket Reel")
    deliver.add_argument("--source", default="storage/generated/pilot/20261119-deutschlandticket-2027-visual")
    sub.add_parser("upload-outbox", help="Upload queued packages. Retains failures locally.")
    sub.add_parser("import-library", help="Record the Reels already rendered in this project")
    install = sub.add_parser("install-cron", help="Write the four Berlin generation cron lines")
    install.add_argument("--apply", action="store_true")
    sub.add_parser("remove-cron", help="Remove the Reel cron block from this user's crontab")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one command. Returns a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in {
        "init-reel-db",
        "reel-status",
        "generate-reel",
        "deliver-existing",
        "upload-outbox",
        "import-library",
        "install-cron",
        "remove-cron",
    }:
        return _reel_command(args)
    try:
        settings = get_settings()
        configure_logging(settings.log_level, settings.log_file)
        ensure_publish_disabled(settings)
        if args.command == "init-db":
            return _init_db()
        if args.command == "status":
            return _status()
        if args.command == "discover":
            return _discover()
    except ValidationError as exc:
        print("configuration error:", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1
    except NewsReelsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"error: unknown command {args.command}", file=sys.stderr)
    return 2


def _reel_command(args: argparse.Namespace) -> int:
    from pathlib import Path

    from app.reels.commands import (
        deliver_existing_command,
        generate_reel_command,
        install_cron_command,
        remove_cron_command,
        status_command,
        upload_outbox_command,
    )
    from app.reels.config import load_reel_config
    from app.reels.store import ReelStore

    if args.command == "init-reel-db":
        config = load_reel_config()
        ReelStore(config.database_path).migrate()
        print(f"Initialized reel database at {config.database_path}")
        return 0
    if args.command == "reel-status":
        return status_command()
    if args.command == "generate-reel":
        return generate_reel_command(scheduled=args.scheduled, target=args.target)
    if args.command == "deliver-existing":
        return deliver_existing_command(Path(args.source))
    if args.command == "upload-outbox":
        return upload_outbox_command()
    if args.command == "import-library":
        from app.reels.catalog import import_library

        imported = import_library(ReelStore(load_reel_config().database_path))
        print("\n".join(imported) if imported else "no reels imported")
        return 0 if imported else 1
    if args.command == "install-cron":
        return install_cron_command(apply=args.apply)
    if args.command == "remove-cron":
        return remove_cron_command()
    print(f"error: unknown command {args.command}", file=sys.stderr)
    return 2


def _init_db() -> int:
    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_media_dirs(settings)
    repository = NewsReelsRepository(settings.database_path)
    repository.initialize(
        client_id=settings.client_id,
        name=settings.client_name,
        timezone_name=settings.timezone,
        daily_reel_limit=settings.daily_reel_limit,
        now=datetime.now(timezone.utc),
    )
    print(f"Initialized database at {settings.database_path.resolve()}")
    return 0


def _status() -> int:
    settings = get_settings()
    if not settings.database_path.exists():
        print("Database is not initialized. Run: python main.py init-db")
        return 1
    repository = NewsReelsRepository(settings.database_path)
    today = production_date(datetime.now(timezone.utc), settings.timezone)
    snapshot = repository.status_snapshot(settings.client_id, today)
    capabilities = probe_ffmpeg(settings.ffmpeg_bin)
    print(render_status(settings, snapshot, capabilities))
    print(json.dumps(health_payload(schema_version=snapshot.schema_version, snapshot=snapshot)))
    return 0


def _discover() -> int:
    from app.services.news.intake import run_intake

    settings = get_settings()
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    ensure_media_dirs(settings)
    repository = NewsReelsRepository(settings.database_path)
    repository.initialize(
        client_id=settings.client_id,
        name=settings.client_name,
        timezone_name=settings.timezone,
        daily_reel_limit=settings.daily_reel_limit,
        now=datetime.now(timezone.utc),
    )
    report = run_intake(settings, repository, now=datetime.now(timezone.utc))
    print(f"articles in window: {report.articles_seen}")
    print(f"translation provider: {report.translation_provider}")
    if report.limitation:
        print(report.limitation)
    if report.failures:
        print("source failures:")
        for failure in report.failures:
            print(f"- {failure.source_name}: {failure.error}")
    if not report.selections:
        print("selections: none")
    else:
        print("selections:")
        for selection in report.selections:
            print(
                f"- rank {selection.rank}: {selection.event_id} "
                f"score {selection.importance_score:.2f} class {selection.story_class}"
            )
    print(f"unfilled ranks: {report.unfilled}")
    return 0


def render_status(settings: Settings, snapshot: StatusSnapshot, capabilities: FFmpegCapabilities) -> str:
    """Format a status report that is safe to print."""

    try:
        encoder = select_encoder(capabilities, settings.video_encoder)
    except NewsReelsError as exc:
        encoder = f"unavailable ({exc})"
    sources = ", ".join(source.name for source in settings.news_sources)
    lines = [
        "Autonomous News Reels",
        f"version: {__version__}",
        f"environment: {settings.app_env}",
        f"client: {settings.client_id}",
        f"timezone: {settings.timezone}",
        f"daily limit: {settings.daily_reel_limit}",
        f"slots: {', '.join(settings.production_slots)}",
        f"effective slot limit: {settings.slot_limit}",
        f"news window hours: {settings.news_window_hours}",
        f"minimum importance: {settings.min_importance_score}",
        f"deduplication fail closed: {settings.fail_closed_deduplication}",
        f"news provider: {settings.news_provider}",
        f"sources: {sources}",
        f"translation provider: {settings.translation_provider}",
        "cross-language matching: entity-and-number hint only; not reliable multilingual deduplication",
        f"image provider: {settings.image_provider}",
        f"tts provider: {settings.tts_provider}",
        f"notification provider: {settings.notification_provider}",
        f"llm provider: {settings.llm_provider}",
        "instagram publish: disabled",
        f"database: {settings.database_path}",
        f"schema: {snapshot.schema_version}",
        f"articles: {snapshot.article_count}",
        f"events: {snapshot.event_count}",
        f"completed today: {snapshot.completed_today}",
        f"content states: {dict(snapshot.content_by_state)}",
        f"ffmpeg: {capabilities.version or capabilities.error}",
        f"video encoder: {encoder}",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
