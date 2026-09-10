"""Future Teams channel adapter using Microsoft Graph."""

from __future__ import annotations

import html
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from notification_service.domain.models import (
    ProviderAccepted,
    ProviderOutcome,
    ProviderRejected,
    TeamsNotification,
)
from notification_service.providers.microsoft_graph._base import GraphProviderBase
from notification_service.providers.microsoft_graph.auth import AccessToken


@dataclass(frozen=True)
class TeamsChannel:
    team_id: str
    channel_id: str

    def __post_init__(self) -> None:
        if not self.team_id or not self.channel_id:
            raise ValueError("Graph Teams channel IDs cannot be empty")


class GraphTeamsProvider(GraphProviderBase):
    """Post channel messages with a delegated ``ChannelMessage.Send`` token.

    Microsoft Graph does not support application permissions for ordinary
    channel-message sends. ``Teamwork.Migrate.All`` is reserved for migration.
    """

    def __init__(
        self,
        destinations: Mapping[str, TeamsChannel],
        token: AccessToken,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        if not destinations:
            raise ValueError("At least one Teams destination must be configured")
        super().__init__(token, client=client, timeout_seconds=timeout_seconds)
        self._destinations = dict(destinations)

    async def send(self, notification: TeamsNotification) -> ProviderOutcome:
        destination = self._destinations.get(notification.destination)
        if destination is None:
            return ProviderRejected(
                "unknown_teams_destination",
                "The Teams destination is not configured",
                False,
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
        try:
            response = await self._client.post(
                url,
                headers=await self._headers(notification.correlation_id),
                json={"body": {"contentType": "html", "content": body}},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return ProviderRejected("graph_network_error", "Connection failed", True)
        except httpx.HTTPError:
            return ProviderRejected(
                "graph_network_error", "Graph operation did not complete", False, False
            )
        if response.status_code == 201:
            try:
                message_id = response.json().get("id")
            except ValueError:
                message_id = None
            return ProviderAccepted(message_id if isinstance(message_id, str) else None)
        return self._rejected(response, "teams_send", known_not_accepted=True)
