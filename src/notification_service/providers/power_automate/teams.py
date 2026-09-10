"""Teams delivery through named Power Automate HTTP-trigger flows."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from notification_service.domain.models import (
    ProviderAccepted,
    ProviderOutcome,
    ProviderRejected,
    TeamsNotification,
)


@dataclass(frozen=True)
class PowerAutomateWebhook:
    """Deployment-owned configuration for one logical Teams destination."""

    endpoint: str = field(repr=False)
    authorization_token: str | None = field(default=None, repr=False)
    headers: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError("Power Automate endpoint must be a valid HTTPS URL")


class PowerAutomateTeamsProvider:
    """Resolve a logical destination and invoke its preconfigured Teams flow."""

    def __init__(
        self,
        destinations: Mapping[str, PowerAutomateWebhook | str],
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        if not destinations:
            raise ValueError("At least one Teams destination must be configured")
        self._destinations = {
            name: value if isinstance(value, PowerAutomateWebhook) else PowerAutomateWebhook(value)
            for name, value in destinations.items()
        }
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=5),
            follow_redirects=False,
            trust_env=True,
        )

    async def send(self, notification: TeamsNotification) -> ProviderOutcome:
        webhook = self._destinations.get(notification.destination)
        if webhook is None:
            return ProviderRejected(
                "unknown_teams_destination",
                "The Teams destination is not configured",
                False,
            )

        headers = {"Content-Type": "application/json", **webhook.headers}
        if webhook.authorization_token:
            headers["Authorization"] = f"Bearer {webhook.authorization_token}"
        payload = {
            "schema_version": 1,
            "correlation_id": notification.correlation_id,
            "idempotency_key": notification.idempotency_key,
            "source_application": notification.source_application,
            "destination": notification.destination,
            "title": notification.title,
            "text": notification.text,
        }
        try:
            response = await self._client.post(webhook.endpoint, headers=headers, json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return ProviderRejected(
                "webhook_network_error", "Connection failed before flow acceptance", True
            )
        except httpx.HTTPError:
            return ProviderRejected(
                "webhook_network_error", "Webhook operation did not complete", False, False
            )

        if response.status_code in {200, 201, 202, 204}:
            return ProviderAccepted(self._message_id(response))
        if response.status_code == 429:
            return ProviderRejected(
                "webhook_throttled",
                "Power Automate throttled the trigger",
                True,
                True,
                self._retry_after(response),
            )
        if 500 <= response.status_code <= 599:
            return ProviderRejected(
                f"webhook_http_{response.status_code}",
                "Power Automate returned a server error",
                False,
                False,
            )
        return ProviderRejected(
            f"webhook_http_{response.status_code}",
            "Power Automate rejected the trigger request",
            False,
            True,
        )

    @staticmethod
    def _message_id(response: httpx.Response) -> str | None:
        try:
            value = response.json()
        except ValueError:
            return None
        if isinstance(value, dict):
            for key in ("provider_message_id", "message_id", "id", "run_id"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate
        return None

    @staticmethod
    def _retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            return max(0.0, (date - datetime.now(UTC)).total_seconds())

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
