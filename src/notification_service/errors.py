"""Stable library exceptions."""


class NotificationError(Exception):
    """Base class for expected notification failures."""


class ValidationError(NotificationError):
    """The request cannot be sent safely."""


class ProviderError(NotificationError):
    """The provider rejected or could not complete a request."""

    def __init__(self, message: str, *, retryable: bool, accepted: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.accepted = accepted


class IdempotencyConflict(NotificationError):
    """A key was reused for different notification content."""
