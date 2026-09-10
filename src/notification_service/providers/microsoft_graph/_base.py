"""Shared HTTP behavior for Microsoft Graph adapters."""

from __future__ import annotations

import ssl

import httpx

from notification_service.domain.models import ProviderRejected
from notification_service.providers.microsoft_graph.auth import AccessToken


class GraphProviderBase:
    def __init__(
        self,
        token: AccessToken,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        self._token = token
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            verify=ssl.create_default_context(),
            timeout=httpx.Timeout(timeout_seconds, connect=5),
            follow_redirects=False,
            trust_env=True,
        )

    async def _headers(self, correlation_id: str) -> dict[str, str]:
        token = await self._token.get()
        return {
            "Authorization": f"Bearer {token}",
            "client-request-id": correlation_id,
        }

    @staticmethod
    def _rejected(
        response: httpx.Response, operation: str, *, known_not_accepted: bool
    ) -> ProviderRejected:
        status = response.status_code
        retry_after = response.headers.get("Retry-After")
        delay = float(retry_after) if retry_after and retry_after.isdigit() else None
        return ProviderRejected(
            f"graph_{operation}_{status}",
            "Microsoft Graph rejected the request",
            status in {408, 429, 500, 502, 503, 504},
            known_not_accepted,
            delay,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        await self._token.aclose()
