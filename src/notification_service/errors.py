"""Compatibility imports for the domain exception module."""

from notification_service.domain.errors import (
    IdempotencyConflict,
    NotificationError,
    ProviderError,
    ValidationError,
)

__all__ = ["IdempotencyConflict", "NotificationError", "ProviderError", "ValidationError"]
