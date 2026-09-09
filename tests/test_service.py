from __future__ import annotations

import pytest

from notification_service.errors import IdempotencyConflict, ValidationError
from notification_service.models import (
    EmailNotification,
    ProviderAccepted,
    ProviderRejected,
    Recipient,
)
from notification_service.service import DeliveryState, NotificationClient


class FakeEmailProvider:
    def __init__(self, *outcomes: ProviderAccepted | ProviderRejected) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    async def send(self, notification: EmailNotification):
        self.calls += 1
        return self.outcomes.pop(0) if self.outcomes else ProviderAccepted("fake")

    async def aclose(self) -> None:
        return None


def message(key: str = "job-1", subject: str = "Ready") -> EmailNotification:
    return EmailNotification((Recipient("ops@contoso.com"),), subject, "Done", idempotency_key=key)


@pytest.mark.asyncio
async def test_acceptance_and_idempotency() -> None:
    provider = FakeEmailProvider(ProviderAccepted("msg-1"))
    client = NotificationClient(provider)
    first = await client.send(message())
    second = await client.send(message())
    assert first.state == DeliveryState.ACCEPTED
    assert first == second
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_retry_only_known_not_accepted() -> None:
    provider = FakeEmailProvider(ProviderRejected("busy", "retry", True), ProviderAccepted("msg-2"))
    result = await NotificationClient(provider).send(message())
    assert result.state == DeliveryState.ACCEPTED
    assert result.attempts == 2


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_not_retried() -> None:
    class Slow:
        calls = 0

        async def send(self, notification: EmailNotification):
            import asyncio

            self.calls += 1
            await asyncio.sleep(1)
            return ProviderAccepted("late")

        async def aclose(self) -> None:
            return None

    provider = Slow()
    result = await NotificationClient(provider, timeout_seconds=0.01).send(message())
    assert result.state == DeliveryState.UNKNOWN
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_key_conflict() -> None:
    provider = FakeEmailProvider()
    client = NotificationClient(provider)
    await client.send(message())
    with pytest.raises(IdempotencyConflict):
        await client.send(message(subject="Changed"))


@pytest.mark.asyncio
async def test_internal_domain_policy() -> None:
    client = NotificationClient(FakeEmailProvider(), allowed_domains=frozenset({"contoso.com"}))
    with pytest.raises(ValidationError):
        await client.send(EmailNotification((Recipient("outside@example.net"),), "No", "No"))
