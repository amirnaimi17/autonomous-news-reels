"""Notification provider that records messages instead of sending them."""

from app.schemas.workflow import NotificationRequest, NotificationResult


class LogNotifier:
    """Keep every notification in memory and report it as delivered."""

    name = "log"

    def __init__(self) -> None:
        self.sent: list[NotificationRequest] = []

    def send(self, message: NotificationRequest) -> NotificationResult:
        self.sent.append(message)
        return NotificationResult(provider=self.name, delivery_status="SENT", detail="recorded")
