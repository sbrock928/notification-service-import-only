from __future__ import annotations

import json

import httpx
import pytest

from notification_service import (
    NotificationTable,
    PowerAutomateTeamsProvider,
    PowerAutomateWebhook,
    TableRenderPolicy,
    TeamsNotification,
)
from notification_service.application import (
    AcceptanceCertainty,
    DeliveryErrorCode,
    DeliveryMetadata,
    ProviderAccepted,
    ProviderFailure,
)

ENDPOINT = "https://prod-00.example.logic.azure.com/trigger?sig=secret"


def metadata() -> DeliveryMetadata:
    return DeliveryMetadata(
        source_application="scheduler",
        correlation_id="corr-1",
        idempotency_key="job-1",
        channel="teams",
    )


def notification(destination: str = "ops-alerts") -> TeamsNotification:
    return TeamsNotification(
        destination=destination,
        title="Job complete",
        text="The job completed.",
        tables=(
            NotificationTable(
                caption="Exceptions",
                columns=("ID", "Reason", "Hidden"),
                rows=(("1", "Bad", "x"), ("2", "Worse", "y")),
            ),
        ),
    )


def provider(client: httpx.AsyncClient, **changes: object) -> PowerAutomateTeamsProvider:
    values: dict[str, object] = {
        "webhook": PowerAutomateWebhook(ENDPOINT),
        "client": client,
    }
    values.update(changes)
    return PowerAutomateTeamsProvider(**values)  # type: ignore[arg-type]


async def test_webhook_card_payload_accepts_any_2xx_and_bounds_tables() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        assert "Authorization" not in request.headers
        return httpx.Response(299, json={"run_id": "run-1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = provider(client, render_policy=TableRenderPolicy(max_rows=1, max_columns=2))
    result = await adapter.send(notification(), metadata())
    await client.aclose()

    assert isinstance(result, ProviderAccepted)
    assert result.provider_message_id == "run-1"
    assert received["type"] == "message"
    attachment = received["attachments"][0]  # type: ignore[index]
    card = attachment["content"]
    assert card["type"] == "AdaptiveCard"
    body = card["body"]
    assert any("1 row(s) omitted" in str(item.get("text")) for item in body)
    assert any("1 column(s) omitted" in str(item.get("text")) for item in body)
    assert any(
        fact["value"] == "corr-1"
        for item in body
        if item.get("type") == "FactSet"
        for fact in item["facts"]
    )


async def test_simple_message_emits_one_adaptive_card() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = provider(client)
    await adapter.send(TeamsNotification(destination="ops-alerts", text="Simple"), metadata())
    await client.aclose()
    assert received["type"] == "message"
    assert len(received["attachments"]) == 1  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://prod.example.com/x?sig=x",
        "https://prod.example.com/x",
        "https://user@prod.example.com/x?sig=x",
        "https://prod.example.com/x?sig=x#fragment",
    ],
)
def test_webhook_requires_signed_https_url(endpoint: str) -> None:
    with pytest.raises(ValueError):
        PowerAutomateWebhook(endpoint)


async def test_provider_uses_one_signed_url_without_host_suffix_configuration() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(202)))
    adapter = PowerAutomateTeamsProvider(
        "https://long-random-host.invalid/trigger?sig=very-long-jumbled-value",
        client=client,
    )
    result = await adapter.send(notification("ops"), metadata())
    await client.aclose()
    assert isinstance(result, ProviderAccepted)


@pytest.mark.parametrize("status", [408, 429, 500, 502])
async def test_ambiguous_statuses_are_not_retryable(status: int) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    result = await provider(client).send(notification(), metadata())
    await client.aclose()
    assert isinstance(result, ProviderFailure)
    assert result.certainty is AcceptanceCertainty.UNKNOWN
    assert result.retryable is False


async def test_certified_429_is_proven_retryable_and_parses_retry_after() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(429, headers={"Retry-After": "12"}))
    )
    adapter = provider(client, throttling_proves_not_accepted=True)
    result = await adapter.send(notification(), metadata())
    await client.aclose()
    assert isinstance(result, ProviderFailure)
    assert result.certainty is AcceptanceCertainty.NOT_ACCEPTED
    assert result.retry_after_seconds == 12


@pytest.mark.parametrize(
    ("status", "code"),
    [(400, DeliveryErrorCode.REQUEST_REJECTED), (401, DeliveryErrorCode.AUTHENTICATION_FAILED)],
)
async def test_definitive_rejections(status: int, code: DeliveryErrorCode) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    result = await provider(client).send(notification(), metadata())
    await client.aclose()
    assert isinstance(result, ProviderFailure)
    assert result.certainty is AcceptanceCertainty.NOT_ACCEPTED
    assert result.error_code is code


@pytest.mark.parametrize(
    ("error_type", "certainty"),
    [
        (httpx.ConnectError, AcceptanceCertainty.NOT_ACCEPTED),
        (httpx.ReadTimeout, AcceptanceCertainty.UNKNOWN),
        (httpx.ProtocolError, AcceptanceCertainty.UNKNOWN),
    ],
)
async def test_network_phase_classification(
    error_type: type[httpx.HTTPError], certainty: AcceptanceCertainty
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_type("network", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    result = await provider(client).send(notification(), metadata())
    await client.aclose()
    assert isinstance(result, ProviderFailure)
    assert result.certainty is certainty
    assert result.retryable is (certainty is AcceptanceCertainty.NOT_ACCEPTED)


async def test_optional_response_id_is_strictly_bounded() -> None:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(202, json={"run_id": "x" * 256}))
    )
    result = await provider(client).send(notification(), metadata())
    await client.aclose()
    assert isinstance(result, ProviderAccepted)
    assert result.provider_message_id is None


async def test_payload_limit_can_reject_unrepresentable_base_message() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(202)))
    adapter = provider(client, render_policy=TableRenderPolicy(teams_payload_bytes=1))
    result = await adapter.send(notification(), metadata())
    assert isinstance(result, ProviderFailure)
    assert result.certainty is AcceptanceCertainty.NOT_ACCEPTED
    await client.aclose()


async def test_provider_owned_http_client_closes() -> None:
    adapter = PowerAutomateTeamsProvider(ENDPOINT)
    assert adapter._client.is_closed is False
    await adapter.aclose()
    assert adapter._client.is_closed is True
