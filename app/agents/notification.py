"""Notification agent contract. Telegram delivery is Phase 6."""

from typing import Protocol

from app.schemas.workflow import NotificationRequest, NotificationResult


class NotificationAgent(Protocol):
    """Tell the owner that a reel was created, skipped, or failed."""

    name: str

    def run(self, request: NotificationRequest) -> NotificationResult:
        """Deliver one notification through the configured provider."""
