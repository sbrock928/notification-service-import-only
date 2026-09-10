"""Stable import-only notification client API."""

from notification_service.application.contracts import (
    DeliveryErrorCode,
    DeliveryResult,
    DeliveryState,
)
from notification_service.application.idempotency import InMemoryIdempotencyStore
from notification_service.application.policies import AllowedEmailDomainsPolicy
from notification_service.application.retry import RetryPolicy
from notification_service.application.service import NotificationClient
from notification_service.client import SyncNotificationClient
from notification_service.domain.errors import (
    ClientClosedError,
    IdempotencyConflict,
    NotificationError,
    ValidationError,
)
from notification_service.domain.models import (
    Attachment,
    EmailNotification,
    NotificationTable,
    Recipient,
    TeamsNotification,
)
from notification_service.presentation.tables import TableRenderPolicy
from notification_service.providers.power_automate import (
    PowerAutomateTeamsProvider,
    PowerAutomateWebhook,
)
from notification_service.providers.win32com import Win32OutlookEmailProvider

__all__ = [
    "AllowedEmailDomainsPolicy",
    "Attachment",
    "ClientClosedError",
    "DeliveryErrorCode",
    "DeliveryResult",
    "DeliveryState",
    "EmailNotification",
    "IdempotencyConflict",
    "InMemoryIdempotencyStore",
    "NotificationClient",
    "NotificationError",
    "NotificationTable",
    "PowerAutomateTeamsProvider",
    "PowerAutomateWebhook",
    "Recipient",
    "RetryPolicy",
    "SyncNotificationClient",
    "TableRenderPolicy",
    "TeamsNotification",
    "ValidationError",
    "Win32OutlookEmailProvider",
]

__version__ = "0.1.0"
