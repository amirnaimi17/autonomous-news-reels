"""Offline providers and reel acceptance rules."""

from datetime import datetime, timedelta, timezone
import wave

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.exceptions import ConfigurationError, VideoValidationError
from app.schemas.news import DiscoveredArticle
from app.schemas.workflow import NotificationRequest, ScriptRequest, SlideVisualRequest, VoiceRequest
from app.services.factory import (
    build_image_provider,
    build_news_source,
    build_notifier,
    build_speech_provider,
    ensure_publish_disabled,
)
from app.services.image_providers.solid import SolidColorImageProvider
from app.services.llm.extractive import build_extractive_script
from app.services.news_sources.static import StaticNewsSource
from app.services.notifications.log import LogNotifier
from app.services.tts_providers.silent import SilentSpeechProvider
from app.services.video.validate import VideoProbe, validate_reel_video


def test_static_source_keeps_only_dated_articles_inside_the_window() -> None:
    now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    source = StaticNewsSource(
        [
            DiscoveredArticle(
                source_name="BBC",
                source_url="https://example.com/new",
                canonical_url="https://example.com/new",
                title="New",
                published_at=now - timedelta(hours=2),
            ),
            DiscoveredArticle(
                source_name="BBC",
                source_url="https://example.com/old",
                canonical_url="https://example.com/old",
                title="Old",
                published_at=now - timedelta(hours=80),
            ),
            DiscoveredArticle(
                source_name="BBC",
                source_url="https://example.com/undated",
                canonical_url="https://example.com/undated",
                title="Undated",
            ),
        ]
    )
    result = source.fetch(window_start=now - timedelta(hours=72), window_end=now)
    assert [article.title for article in result.articles] == ["New"]


def test_extractive_script_copies_source_sentences_and_does_not_pad() -> None:
    script = build_extractive_script(
        ScriptRequest(
            event_id="event-1",
            title="Central bank holds rates",
            summary=(
                "The central bank held rates at 4.5 percent. "
                "Officials said inflation is easing. "
                "Markets had expected no change. "
                "The next decision is scheduled for December."
            ),
            source_name="BBC World",
            source_url="https://example.com/rates",
            published_at=datetime(2026, 11, 18, 7, tzinfo=timezone.utc),
        )
    )
    assert script.provider == "extractive"
    assert len(script.script.slides) == 4
    assert "4.5" in script.script.full_narration
    short = build_extractive_script(
        ScriptRequest(
            event_id="event-2",
            title="Port reopens",
            summary="<p>The port reopened after the storm.</p>",
            source_name="BBC World",
            source_url="https://example.com/port",
        )
    )
    assert len(short.script.slides) == 1
    assert "<p>" not in short.script.full_narration
    with pytest.raises(ValidationError):
        build_extractive_script(
            ScriptRequest(
                event_id="event-3",
                title="Missing source",
                summary="A fact.",
                source_name="BBC",
                source_url="not-a-url",
            )
        )


def test_solid_image_and_silent_audio_write_real_files(tmp_path) -> None:
    image = SolidColorImageProvider().generate(
        SlideVisualRequest(
            slide_index=1,
            headline="Central bank holds rates",
            visual_brief="Typographic card",
            output_path=str(tmp_path / "slide.ppm"),
        ),
        width=10,
        height=16,
    )
    payload = (tmp_path / "slide.ppm").read_bytes()
    assert payload.startswith(b"P6\n10 16\n255\n")
    assert len(payload) == len(b"P6\n10 16\n255\n") + 10 * 16 * 3
    assert image.provider == "solid"

    speech = SilentSpeechProvider(sample_rate=8000).synthesize(
        VoiceRequest(content_id="content-1", narration="The bank held rates today.", output_path=str(tmp_path / "voice.wav"))
    )
    assert speech.duration_seconds >= 1.5
    with wave.open(str(tmp_path / "voice.wav")) as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 8000
        assert handle.getnframes() > 0


def test_log_notifier_records_the_message() -> None:
    notifier = LogNotifier()
    message = NotificationRequest(
        client_id="default",
        headline="Central bank holds rates",
        status="COMPLETED",
        detail="Reel written to storage/videos/reel.mp4",
        video_path="storage/videos/reel.mp4",
    )
    result = notifier.send(message)
    assert result.delivery_status == "SENT"
    assert notifier.sent == [message]


def test_unbuilt_providers_fail_closed() -> None:
    rss = Settings(_env_file=None, news_provider="rss")
    with pytest.raises(ConfigurationError):
        build_news_source(rss)
    telegram = Settings(_env_file=None, notification_provider="telegram")
    with pytest.raises(ConfigurationError):
        build_notifier(telegram)
    with pytest.raises(ConfigurationError):
        ensure_publish_disabled(Settings(_env_file=None, instagram_publish_enabled=True))
    assert build_image_provider(Settings(_env_file=None)).name == "solid"
    assert build_speech_provider(Settings(_env_file=None)).name == "silent"
    assert build_notifier(Settings(_env_file=None)).name == "log"


def test_reel_validator_accepts_a_vertical_h264_file_and_rejects_the_rest() -> None:
    good = VideoProbe(1080, 1920, 24, "h264", "aac", True)
    validate_reel_video(good, expected_width=1080, expected_height=1920, min_duration=8, max_duration=90)
    with pytest.raises(VideoValidationError):
        validate_reel_video(
            VideoProbe(720, 1280, 24, "h264", "aac", True),
            expected_width=1080,
            expected_height=1920,
            min_duration=8,
            max_duration=90,
        )
    with pytest.raises(VideoValidationError):
        validate_reel_video(
            VideoProbe(1080, 1920, 24, "h264", None, False),
            expected_width=1080,
            expected_height=1920,
            min_duration=8,
            max_duration=90,
        )
    with pytest.raises(VideoValidationError):
        validate_reel_video(
            VideoProbe(1080, 1920, 2, "h264", "aac", True),
            expected_width=1080,
            expected_height=1920,
            min_duration=8,
            max_duration=90,
        )
