"""Stable, provider-independent library exceptions."""


class NotificationError(Exception):
    """Base class for expected notification failures."""


class ValidationError(NotificationError):
    """Notification content or a policy configuration is unsafe."""


class IdempotencyConflict(NotificationError):
    """An idempotency key was reused for different notification content."""


class ClientClosedError(NotificationError):
    """A delivery was requested after client shutdown began."""


class ProviderError(NotificationError):
    """Legacy provider exception retained as an advanced compatibility guard."""

    def __init__(self, message: str, *, retryable: bool, accepted: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.accepted = accepted
