"""Compatibility imports for application provider ports."""

from notification_service.application.ports import NotificationProvider

EmailProvider = NotificationProvider

__all__ = ["EmailProvider", "NotificationProvider"]
