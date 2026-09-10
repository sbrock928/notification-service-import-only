"""Provider-neutral notification domain."""

from notification_service.domain.errors import (
    ClientClosedError,
    IdempotencyConflict,
    NotificationError,
    ProviderError,
    ValidationError,
)
from notification_service.domain.models import (
    Attachment,
    EmailNotification,
    Notification,
    NotificationTable,
    Recipient,
    TeamsNotification,
)

__all__ = [
    "Attachment",
    "ClientClosedError",
    "EmailNotification",
    "IdempotencyConflict",
    "Notification",
    "NotificationError",
    "NotificationTable",
    "ProviderError",
    "Recipient",
    "TeamsNotification",
    "ValidationError",
]
