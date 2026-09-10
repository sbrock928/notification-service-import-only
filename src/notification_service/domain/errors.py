"""Stable, provider-independent library exceptions."""


class NotificationError(Exception):
    """Base class for expected notification failures."""


class ValidationError(NotificationError):
    """The request cannot be sent safely."""


class ProviderError(NotificationError):
    """A provider raised instead of returning a normalized outcome."""

    def __init__(self, message: str, *, retryable: bool, accepted: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.accepted = accepted


class IdempotencyConflict(NotificationError):
    """An idempotency key was reused for different notification content."""
