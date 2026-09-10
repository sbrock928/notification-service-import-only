"""Shared experimental Graph HTTP behavior."""

from __future__ import annotations

import httpx

from notification_service.application.contracts import (
    AcceptanceCertainty,
    DeliveryErrorCode,
    ProviderFailure,
)
from notification_service.experimental.graph.auth import AccessToken


class GraphProviderBase:
    def __init__(
        self,
        token: AccessToken,
        *,
        client: httpx.AsyncClient | None = None,
        owns_token: bool = False,
    ) -> None:
        self._token = token
        self._owns_token = owns_token
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5, pool=5, read=30, write=30),
            follow_redirects=False,
            trust_env=True,
        )

    async def _headers(self, correlation_id: str) -> dict[str, str] | ProviderFailure:
        try:
            token = await self._token.get()
        except Exception:
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.AUTHENTICATION_FAILED,
                diagnostic_code="graph_token_failed",
            )
        return {"Authorization": f"Bearer {token}", "client-request-id": correlation_id}

    @staticmethod
    def _response_failure(
        response: httpx.Response,
        operation: str,
        *,
        request_could_be_accepted: bool,
    ) -> ProviderFailure:
        status = response.status_code
        unknown = request_could_be_accepted and (status == 408 or status == 429 or status >= 500)
        if status in {401, 403}:
            error = DeliveryErrorCode.AUTHENTICATION_FAILED
        elif status == 429:
            error = DeliveryErrorCode.THROTTLED
        elif unknown:
            error = DeliveryErrorCode.DELIVERY_AMBIGUOUS
        else:
            error = DeliveryErrorCode.REQUEST_REJECTED
        return ProviderFailure(
            certainty=AcceptanceCertainty.UNKNOWN if unknown else AcceptanceCertainty.NOT_ACCEPTED,
            error_code=error,
            retryable=(not request_could_be_accepted and status in {408, 429, 500, 502, 503, 504}),
            diagnostic_code=f"graph_{operation}_{status}",
        )

    @staticmethod
    def _network_failure(*, request_could_be_accepted: bool) -> ProviderFailure:
        return ProviderFailure(
            certainty=(
                AcceptanceCertainty.UNKNOWN
                if request_could_be_accepted
                else AcceptanceCertainty.NOT_ACCEPTED
            ),
            error_code=(
                DeliveryErrorCode.DELIVERY_AMBIGUOUS
                if request_could_be_accepted
                else DeliveryErrorCode.PROVIDER_UNAVAILABLE
            ),
            retryable=not request_could_be_accepted,
            diagnostic_code="graph_network_failure",
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
        if self._owns_token:
            await self._token.aclose()
