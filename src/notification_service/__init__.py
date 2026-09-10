"""Import-only notification client with replaceable Microsoft transports."""

from notification_service.application.service import (
    DeliveryResult,
    DeliveryState,
    InMemoryIdempotencyStore,
    NotificationClient,
)
from notification_service.client import SyncNotificationClient
from notification_service.domain.models import (
    Attachment,
    EmailNotification,
    Recipient,
    TeamsNotification,
)
from notification_service.providers.microsoft_graph import (
    ClientSecretToken,
    GraphEmailProvider,
    GraphTeamsProvider,
    TeamsChannel,
)
from notification_service.providers.power_automate import (
    PowerAutomateTeamsProvider,
    PowerAutomateWebhook,
)
from notification_service.providers.win32com import Win32OutlookEmailProvider

__all__ = [
    "Attachment",
    "ClientSecretToken",
    "DeliveryResult",
    "DeliveryState",
    "EmailNotification",
    "GraphEmailProvider",
    "GraphTeamsProvider",
    "InMemoryIdempotencyStore",
    "NotificationClient",
    "PowerAutomateTeamsProvider",
    "PowerAutomateWebhook",
    "Recipient",
    "SyncNotificationClient",
    "TeamsChannel",
    "TeamsNotification",
    "Win32OutlookEmailProvider",
]

__version__ = "0.1.0"
