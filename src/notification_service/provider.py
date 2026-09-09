"""Provider port used by the application service and fakes in tests."""

from __future__ import annotations

from typing import Protocol

from notification_service.models import EmailNotification, ProviderOutcome


class EmailProvider(Protocol):
    async def send(self, notification: EmailNotification) -> ProviderOutcome: ...

    async def aclose(self) -> None: ...
