from __future__ import annotations

import json

import httpx

from notification_service.models import (
    EmailNotification,
    ProviderAccepted,
    ProviderRejected,
    Recipient,
)
from notification_service.power_automate import PowerAutomateEmailProvider


def notification() -> EmailNotification:
    return EmailNotification(
        (Recipient("ops@contoso.com"),),
        "Job complete",
        "The job completed.",
        idempotency_key="job-1",
    )


async def test_webhook_payload_and_acceptance() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer user-token"
        return httpx.Response(202, json={"run_id": "run-1"})

    provider = PowerAutomateEmailProvider(
        "https://prod-00.example.logic.azure.com/trigger",
        authorization_token="user-token",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await provider.send(notification())
    await provider.aclose()

    assert isinstance(result, ProviderAccepted)
    assert result.provider_message_id == "run-1"
    assert received["idempotency_key"] == "job-1"


async def test_webhook_server_error_is_unknown() -> None:
    provider = PowerAutomateEmailProvider(
        "https://prod-00.example.logic.azure.com/trigger",
        client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(502))
        ),
    )
    result = await provider.send(notification())
    await provider.aclose()

    assert isinstance(result, ProviderRejected)
    assert result.known_not_accepted is False
    assert result.retryable is False
