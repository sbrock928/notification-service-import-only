from __future__ import annotations

import json

import httpx

from notification_service import EmailNotification, Recipient, TeamsNotification
from notification_service.models import ProviderAccepted, ProviderRejected
from notification_service.providers.microsoft_graph import (
    GraphEmailProvider,
    GraphTeamsProvider,
    TeamsChannel,
)


class FakeToken:
    closed = False

    async def get(self) -> str:
        return "access-token"

    async def invalidate(self) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


async def test_graph_email_uses_same_email_model() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/messages"):
            return httpx.Response(201, json={"id": "draft-1"})
        return httpx.Response(202)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    token = FakeToken()
    provider = GraphEmailProvider("shared@contoso.com", token, client=http_client)
    result = await provider.send(
        EmailNotification((Recipient("ops@contoso.com"),), "Job failed", "Inspect logs")
    )
    await provider.aclose()
    await http_client.aclose()

    assert isinstance(result, ProviderAccepted)
    assert result.provider_message_id == "draft-1"
    assert requests[0].headers["Authorization"] == "Bearer access-token"
    assert requests[1].url.path.endswith("/messages/draft-1/send")
    assert token.closed is True


async def test_graph_teams_preserves_logical_destination() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        assert request.url.path == "/v1.0/teams/team-1/channels/channel-1/messages"
        return httpx.Response(201, json={"id": "teams-message-1"})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GraphTeamsProvider(
        {"ops-alerts": TeamsChannel("team-1", "channel-1")},
        FakeToken(),
        client=http_client,
    )
    result = await provider.send(
        TeamsNotification("ops-alerts", "Inspect <logs>", title="Job failed")
    )
    await http_client.aclose()

    assert isinstance(result, ProviderAccepted)
    assert result.provider_message_id == "teams-message-1"
    assert received == {
        "body": {
            "contentType": "html",
            "content": "<strong>Job failed</strong><br>Inspect &lt;logs&gt;",
        }
    }


async def test_graph_teams_rejects_unknown_destination_without_http() -> None:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    provider = GraphTeamsProvider(
        {"ops-alerts": TeamsChannel("team-1", "channel-1")},
        FakeToken(),
        client=http_client,
    )
    result = await provider.send(TeamsNotification("data-quality", "Not configured"))
    await http_client.aclose()

    assert isinstance(result, ProviderRejected)
    assert result.code == "unknown_teams_destination"
