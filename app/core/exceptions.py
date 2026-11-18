"""Application errors.

Callers catch NewsReelsError at process boundaries. Narrower types exist so
quota, duplicate, and validation failures can be handled differently.
"""


class NewsReelsError(Exception):
    """Base error for expected application failures."""


class ConfigurationError(NewsReelsError):
    """The process cannot start with the current settings."""


class PersistenceError(NewsReelsError):
    """The database rejected or could not complete a write."""


class NotFoundError(PersistenceError):
    """The requested row does not exist."""


class DuplicateStoryError(PersistenceError):
    """The event already has a reel or is owned by another run."""


class DuplicateEventError(PersistenceError):
    """An event with this fingerprint is already stored."""


class ArticleAlreadyLinkedError(PersistenceError):
    """The article is already attached to a different event."""


class QuotaExceededError(PersistenceError):
    """The client already reached the daily reel limit."""


class SlotUnavailableError(PersistenceError):
    """This production slot cannot be reserved."""


class InvalidStateTransitionError(PersistenceError):
    """The generation state machine rejected the next state."""


class GroundingError(NewsReelsError):
    """A narration introduced a figure that is not present in the source."""


class VideoValidationError(NewsReelsError):
    """A rendered file failed the reel acceptance checks."""
