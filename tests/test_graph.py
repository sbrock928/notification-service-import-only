from __future__ import annotations

import json
import sys
import types

import httpx

from notification_service import EmailNotification, NotificationTable, Recipient, TeamsNotification
from notification_service.application import DeliveryMetadata, ProviderAccepted, ProviderFailure
from notification_service.experimental.graph import (
    ClientSecretToken,
    GraphEmailProvider,
    GraphTeamsProvider,
    TeamsChannel,
)


class FakeToken:
    def __init__(self, *, fail: bool = False) -> None:
        self.closed = False
        self.fail = fail

    async def get(self) -> str:
        if self.fail:
            raise RuntimeError("no token")
        return "access-token"

    async def invalidate(self) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True


def metadata(channel: str) -> DeliveryMetadata:
    return DeliveryMetadata(
        source_application="worker",
        correlation_id="corr",
        idempotency_key=None,
        channel=channel,
    )


async def test_graph_email_uses_rendered_tables_and_borrowed_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/messages"):
            body = json.loads(request.content)
            assert "&lt;bad&gt;" in body["body"]["content"]
            return httpx.Response(201, json={"id": "draft-1"})
        return httpx.Response(202)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    token = FakeToken()
    provider = GraphEmailProvider("shared@contoso.com", token, client=client)
    result = await provider.send(
        EmailNotification(
            to=(Recipient("ops@contoso.com"),),
            subject="Failed",
            text="Inspect",
            tables=(NotificationTable(columns=("Reason",), rows=(("<bad>",),)),),
        ),
        metadata("email"),
    )
    await provider.aclose()
    await client.aclose()
    assert isinstance(result, ProviderAccepted)
    assert result.provider_message_id == "draft-1"
    assert requests[0].headers["Authorization"] == "Bearer access-token"
    assert token.closed is False


async def test_graph_explicit_token_ownership_and_auth_failure() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    token = FakeToken(fail=True)
    provider = GraphEmailProvider("shared@contoso.com", token, client=client, owns_token=True)
    result = await provider.send(
        EmailNotification(to=(Recipient("ops@contoso.com"),), subject="x", text="x"),
        metadata("email"),
    )
    await provider.aclose()
    await client.aclose()
    assert isinstance(result, ProviderFailure)
    assert token.closed


async def test_graph_teams_preserves_destination_and_escapes_content() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        assert request.url.path == "/v1.0/teams/team-1/channels/channel-1/messages"
        return httpx.Response(201, json={"id": "message-1"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GraphTeamsProvider(
        {"ops": TeamsChannel("team-1", "channel-1")},
        FakeToken(),
        client=client,
    )
    result = await provider.send(
        TeamsNotification(destination="ops", text="Inspect <logs>", title="Failed"),
        metadata("teams"),
    )
    await client.aclose()
    assert isinstance(result, ProviderAccepted)
    assert "Inspect &lt;logs&gt;" in received["body"]["content"]  # type: ignore[index]


async def test_graph_teams_unknown_destination_is_local_failure() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    provider = GraphTeamsProvider(
        {"ops": TeamsChannel("team", "channel")}, FakeToken(), client=client
    )
    result = await provider.send(
        TeamsNotification(destination="missing", text="x"), metadata("teams")
    )
    await client.aclose()
    assert isinstance(result, ProviderFailure)


async def test_client_secret_token_is_lazy_and_closeable(monkeypatch: object) -> None:
    events: list[str] = []

    class Credential:
        def __init__(self, tenant: str, client: str, secret: str) -> None:
            events.append(f"create:{tenant}:{client}:{secret}")

        async def get_token(self, scope: str) -> object:
            events.append(scope)
            return types.SimpleNamespace(token="token")

        async def close(self) -> None:
            events.append("close")

    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    aio = types.ModuleType("azure.identity.aio")
    aio.ClientSecretCredential = Credential  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure", azure)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure.identity", identity)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure.identity.aio", aio)  # type: ignore[attr-defined]
    token = ClientSecretToken("tenant", "client", "secret")
    assert events == []
    assert await token.get() == "token"
    await token.invalidate()
    await token.aclose()
    assert events[-1] == "close"


async def test_graph_email_draft_and_attachment_failures_cleanup() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path.endswith("/messages"):
            return httpx.Response(201, json={"id": "draft"})
        if request.url.path.endswith("/attachments"):
            return httpx.Response(400)
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GraphEmailProvider("box@contoso.com", FakeToken(), client=client)
    result = await provider.send(
        EmailNotification(
            to=(Recipient("ops@contoso.com"),),
            subject="x",
            text="x",
            attachments=(
                __import__("notification_service").Attachment("x.txt", "text/plain", b"x"),
            ),
        ),
        metadata("email"),
    )
    await client.aclose()
    assert isinstance(result, ProviderFailure)
    assert "DELETE" in methods


async def test_graph_email_large_attachment_upload_and_send() -> None:
    ranges: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            return httpx.Response(201, json={"id": "draft"})
        if request.url.path.endswith("createUploadSession"):
            return httpx.Response(
                201, json={"uploadUrl": "https://upload.outlook.office.com/value"}
            )
        if request.method == "PUT":
            ranges.append(request.headers["Content-Range"])
            return httpx.Response(201)
        if request.url.path.endswith("/send"):
            return httpx.Response(202)
        return httpx.Response(204)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GraphEmailProvider("box@contoso.com", FakeToken(), client=client)
    attachment_type = __import__("notification_service").Attachment
    result = await provider.send(
        EmailNotification(
            to=(Recipient("ops@contoso.com"),),
            subject="x",
            text="x",
            attachments=(
                attachment_type("large.bin", "application/octet-stream", b"x" * 3_000_001),
            ),
        ),
        metadata("email"),
    )
    await client.aclose()
    assert isinstance(result, ProviderAccepted)
    assert ranges == ["bytes 0-3000000/3000001"]


async def test_graph_email_rejects_malformed_provider_values() -> None:
    responses = iter(
        [
            httpx.Response(201, json={}),
            httpx.Response(400),
        ]
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: next(responses)))
    provider = GraphEmailProvider("box@contoso.com", FakeToken(), client=client)
    message = EmailNotification(to=(Recipient("ops@contoso.com"),), subject="x", text="x")
    first = await provider.send(message, metadata("email"))
    second = await provider.send(message, metadata("email"))
    await client.aclose()
    assert isinstance(first, ProviderFailure)
    assert isinstance(second, ProviderFailure)


async def test_graph_email_network_failure_is_normalized() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GraphEmailProvider("box@contoso.com", FakeToken(), client=client)
    result = await provider.send(
        EmailNotification(to=(Recipient("ops@contoso.com"),), subject="x", text="x"),
        metadata("email"),
    )
    await client.aclose()
    assert isinstance(result, ProviderFailure)


async def test_graph_teams_tables_status_and_malformed_id_paths() -> None:
    received: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(json.loads(request.content))
        return httpx.Response(201, content=b"not-json")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = GraphTeamsProvider(
        {"ops": TeamsChannel("team", "channel")}, FakeToken(), client=client
    )
    result = await provider.send(
        TeamsNotification(
            destination="ops",
            text="x",
            tables=(NotificationTable(columns=("A",), rows=(("<value>",), ("second",))),),
        ),
        metadata("teams"),
    )
    await client.aclose()
    assert isinstance(result, ProviderAccepted)
    assert result.provider_message_id is None
    assert "&lt;value&gt;" in received["body"]["content"]  # type: ignore[index]


async def test_graph_teams_http_rejection_and_network_error() -> None:
    for handler in (
        lambda _: httpx.Response(503),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("lost", request=request)),
    ):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = GraphTeamsProvider(
            {"ops": TeamsChannel("team", "channel")}, FakeToken(), client=client
        )
        result = await provider.send(
            TeamsNotification(destination="ops", text="x"), metadata("teams")
        )
        await client.aclose()
        assert isinstance(result, ProviderFailure)
