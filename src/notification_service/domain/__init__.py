"""Provider-independent notification domain objects."""

from notification_service.domain.errors import (
    IdempotencyConflict,
    NotificationError,
    ProviderError,
    ValidationError,
)
from notification_service.domain.models import (
    Attachment,
    EmailNotification,
    Notification,
    ProviderAccepted,
    ProviderOutcome,
    ProviderRejected,
    Recipient,
    TeamsNotification,
)

__all__ = [
    "Attachment",
    "EmailNotification",
    "IdempotencyConflict",
    "Notification",
    "NotificationError",
    "ProviderAccepted",
    "ProviderError",
    "ProviderOutcome",
    "ProviderRejected",
    "Recipient",
    "TeamsNotification",
    "ValidationError",
]
