"""Power Automate webhook adapter for the import-only client.

The flow owns the Outlook connector and its user connection.  This adapter only
posts a bounded, provider-neutral email payload to the configured trigger.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping
from email.utils import parsedate_to_datetime

import httpx

from notification_service.models import (
    EmailNotification,
    ProviderAccepted,
    ProviderOutcome,
    ProviderRejected,
)


class PowerAutomateEmailProvider:
    """Send email by invoking a configured Power Automate HTTP trigger.

    ``authorization_token`` is an interim user token.  Production deployments
    should replace it with a service identity or an appropriately protected
    flow trigger without changing the client or notification model.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        authorization_token: str | None = None,
        headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("Power Automate endpoint must use HTTPS")
        self.endpoint = endpoint
        self._authorization_token = authorization_token
        self._headers = dict(headers or {})
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=5),
            follow_redirects=False,
            trust_env=True,
        )

    async def send(self, notification: EmailNotification) -> ProviderOutcome:
        payload = {
            "schema_version": 1,
            "correlation_id": notification.correlation_id,
            "idempotency_key": notification.idempotency_key,
            "source_application": notification.source_application,
            "to": [item.address for item in notification.to],
            "cc": [item.address for item in notification.cc],
            "bcc": [item.address for item in notification.bcc],
            "subject": notification.subject,
            "text": notification.text,
            "html": notification.html,
            "attachments": [
                {
                    "filename": item.filename,
                    "media_type": item.media_type,
                    "content_base64": base64.b64encode(item.content).decode("ascii"),
                }
                for item in notification.attachments
            ],
        }
        request_headers = {"Content-Type": "application/json", **self._headers}
        if self._authorization_token:
            request_headers["Authorization"] = f"Bearer {self._authorization_token}"
        try:
            response = await self.client.post(
                self.endpoint,
                headers=request_headers,
                json=payload,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return ProviderRejected("webhook_network_error", "Connection failed before flow acceptance", True)
        except httpx.HTTPError:
            return ProviderRejected("webhook_network_error", "Webhook operation did not complete", False)

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
            # A flow may have started even when its HTTP response is a 5xx.
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
            from datetime import UTC, datetime

            return max(0.0, (date - datetime.now(UTC)).total_seconds())

    async def aclose(self) -> None:
        await self.client.aclose()
