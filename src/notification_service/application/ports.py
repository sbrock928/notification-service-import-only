"""Ports implemented by infrastructure adapters and persistence fakes."""

from __future__ import annotations

from typing import Protocol, TypeVar

from notification_service.domain.models import Notification, ProviderOutcome

NotificationT_contra = TypeVar("NotificationT_contra", bound=Notification, contravariant=True)


class NotificationProvider(Protocol[NotificationT_contra]):
    async def send(self, notification: NotificationT_contra) -> ProviderOutcome: ...

    async def aclose(self) -> None: ...
