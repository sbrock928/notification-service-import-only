"""Advanced ports implemented by infrastructure adapters and durable stores."""

from __future__ import annotations

from typing import Protocol, TypeVar

from notification_service.application.contracts import DeliveryMetadata, ProviderOutcome
from notification_service.domain.models import Notification

NotificationT_contra = TypeVar("NotificationT_contra", bound=Notification, contravariant=True)


class NotificationProvider(Protocol[NotificationT_contra]):
    async def send(
        self,
        notification: NotificationT_contra,
        metadata: DeliveryMetadata,
    ) -> ProviderOutcome: ...

    async def aclose(self) -> None: ...
