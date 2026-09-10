"""Research-only delegated Graph Teams channel adapter."""

from __future__ import annotations

import html
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from notification_service.application.contracts import (
    AcceptanceCertainty,
    DeliveryErrorCode,
    DeliveryMetadata,
    ProviderAccepted,
    ProviderFailure,
    ProviderOutcome,
)
from notification_service.domain.models import TeamsNotification
from notification_service.experimental.graph._base import GraphProviderBase
from notification_service.experimental.graph.auth import AccessToken
from notification_service.presentation.tables import TableRenderPolicy, bound_tables


@dataclass(frozen=True, slots=True)
class TeamsChannel:
    team_id: str
    channel_id: str

    def __post_init__(self) -> None:
        if not self.team_id or not self.channel_id:
            raise ValueError("Graph Teams channel IDs cannot be empty")


class GraphTeamsProvider(GraphProviderBase):
    """Post with delegated `ChannelMessage.Send`; never migration permission."""

    def __init__(
        self,
        destinations: Mapping[str, TeamsChannel],
        token: AccessToken,
        *,
        client: httpx.AsyncClient | None = None,
        owns_token: bool = False,
        render_policy: TableRenderPolicy | None = None,
    ) -> None:
        if not destinations:
            raise ValueError("At least one Teams destination must be configured")
        super().__init__(token, client=client, owns_token=owns_token)
        self._destinations = dict(destinations)
        self._render_policy = render_policy or TableRenderPolicy()

    async def send(
        self,
        notification: TeamsNotification,
        metadata: DeliveryMetadata,
    ) -> ProviderOutcome:
        destination = self._destinations.get(notification.destination)
        if destination is None:
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.DESTINATION_NOT_CONFIGURED,
                diagnostic_code="graph_teams_destination_missing",
            )
        url = (
            "https://graph.microsoft.com/v1.0/teams/"
            + quote(destination.team_id, safe="")
            + "/channels/"
            + quote(destination.channel_id, safe="")
            + "/messages"
        )
        body = html.escape(notification.text).replace("\n", "<br>")
        if notification.title:
            body = f"<strong>{html.escape(notification.title)}</strong><br>{body}"
        for table in bound_tables(notification.tables, self._render_policy):
            body += "<br><table><thead><tr>"
            body += "".join(f"<th>{html.escape(column)}</th>" for column in table.columns)
            body += "</tr></thead><tbody>"
            body += "".join(
                "<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>"
                for row in table.rows
            )
            body += "</tbody></table>"
            if table.omitted_rows or table.omitted_columns:
                body += (
                    f"<br>Omitted: {table.omitted_rows} row(s), {table.omitted_columns} column(s)."
                )
        headers = await self._headers(metadata.correlation_id)
        if isinstance(headers, ProviderFailure):
            return headers
        try:
            response = await self._client.post(
                url,
                headers=headers,
                json={"body": {"contentType": "html", "content": body}},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return self._network_failure(request_could_be_accepted=False)
        except httpx.HTTPError:
            return self._network_failure(request_could_be_accepted=True)
        if response.status_code == 201:
            try:
                message_id = response.json().get("id")
            except (AttributeError, ValueError):
                message_id = None
            return ProviderAccepted(
                provider_message_id=message_id if isinstance(message_id, str) else None
            )
        return self._response_failure(
            response,
            "teams_send",
            request_could_be_accepted=True,
        )
