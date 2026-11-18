"""Construct the configured providers.

Unknown providers and providers that are not built yet fail here. They do not
silently switch to another implementation.
"""

from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.services.image_providers.solid import SolidColorImageProvider
from app.services.news.sources import configured_news_sources
from app.services.news_sources.rss import RssNewsSource, UrllibTransport
from app.services.news_sources.static import StaticNewsSource
from app.services.notifications.log import LogNotifier
from app.services.tts_providers.silent import SilentSpeechProvider


def build_news_source(settings: Settings) -> StaticNewsSource | RssNewsSource:
    """Return the configured news source.

    RSS with no sources is a configuration error. There is no built-in feed list.
    """

    if settings.news_provider == "static":
        return StaticNewsSource(())
    if settings.news_provider == "rss":
        sources = configured_news_sources(settings)
        if not sources:
            raise ConfigurationError(
                "NEWS_PROVIDER=rss requires NEWS_SOURCES or NEWS_SOURCES_FILE. "
                "No default feeds are configured."
            )
        return RssNewsSource(
            sources,
            UrllibTransport(timeout=settings.http_timeout_seconds, user_agent=settings.http_user_agent),
        )
    raise ConfigurationError(f"unknown news provider: {settings.news_provider}")


def build_image_provider(settings: Settings) -> SolidColorImageProvider:
    if settings.image_provider == "solid":
        return SolidColorImageProvider()
    raise ConfigurationError(f"unknown image provider: {settings.image_provider}")


def build_speech_provider(settings: Settings) -> SilentSpeechProvider:
    if settings.tts_provider == "silent":
        return SilentSpeechProvider()
    raise ConfigurationError(f"unknown TTS provider: {settings.tts_provider}")


def build_notifier(settings: Settings) -> LogNotifier:
    if settings.notification_provider == "log":
        return LogNotifier()
    if settings.notification_provider == "telegram":
        raise ConfigurationError(
            "Telegram delivery is not implemented yet. Keep NOTIFICATION_PROVIDER=log until Phase 6."
        )
    raise ConfigurationError(f"unknown notification provider: {settings.notification_provider}")


def ensure_publish_disabled(settings: Settings) -> None:
    """Refuse to start when Instagram publishing is turned on before it exists."""

    if settings.instagram_publish_enabled:
        raise ConfigurationError(
            "Instagram publishing is not available in this version. "
            "Set INSTAGRAM_PUBLISH_ENABLED=false."
        )
