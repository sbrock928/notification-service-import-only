"""Import-only notification client. Importing this package starts no network or background work."""

from notification_service.client import SyncNotificationClient
from notification_service.models import Attachment, EmailNotification, Recipient
from notification_service.outlook import GraphEmailProvider
from notification_service.power_automate import PowerAutomateEmailProvider
from notification_service.service import DeliveryResult, DeliveryState, NotificationClient

__all__ = [
    "Attachment",
    "DeliveryResult",
    "DeliveryState",
    "EmailNotification",
    "GraphEmailProvider",
    "NotificationClient",
    "PowerAutomateEmailProvider",
    "Recipient",
    "SyncNotificationClient",
]

__version__ = "0.1.0"
