from __future__ import annotations

import json

import httpx

from notification_service import (
    PowerAutomateTeamsProvider,
    PowerAutomateWebhook,
    TeamsNotification,
)
from notification_service.models import ProviderAccepted, ProviderRejected


def notification(destination: str = "ops-alerts") -> TeamsNotification:
    return TeamsNotification(
        destination=destination,
        title="Job complete",
        text="The job completed.",
        idempotency_key="job-1",
        source_application="scheduler",
    )


async def test_webhook_payload_and_acceptance() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer user-token"
        return httpx.Response(202, json={"run_id": "run-1"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = PowerAutomateTeamsProvider(
        {
            "ops-alerts": PowerAutomateWebhook(
                "https://prod-00.example.logic.azure.com/trigger",
                authorization_token="user-token",
            )
        },
        client=http_client,
    )
    result = await provider.send(notification())
    await provider.aclose()
    await http_client.aclose()

    assert isinstance(result, ProviderAccepted)
    assert result.provider_message_id == "run-1"
    assert received["destination"] == "ops-alerts"
    assert received["idempotency_key"] == "job-1"


async def test_unknown_destination_is_rejected_without_http_request() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(202)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = PowerAutomateTeamsProvider(
        {"ops-alerts": "https://prod-00.example.logic.azure.com/trigger"},
        client=http_client,
    )
    result = await provider.send(notification("not-configured"))
    await http_client.aclose()

    assert isinstance(result, ProviderRejected)
    assert result.code == "unknown_teams_destination"
    assert calls == 0


async def test_webhook_server_error_is_unknown() -> None:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(502)))
    provider = PowerAutomateTeamsProvider(
        {"ops-alerts": "https://prod-00.example.logic.azure.com/trigger"},
        client=http_client,
    )
    result = await provider.send(notification())
    await http_client.aclose()

    assert isinstance(result, ProviderRejected)
    assert result.known_not_accepted is False
    assert result.retryable is False
