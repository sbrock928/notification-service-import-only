"""Teams delivery through non-premium Power Automate Teams webhook workflows."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx

from notification_service.application.contracts import (
    AcceptanceCertainty,
    DeliveryErrorCode,
    DeliveryMetadata,
    ProviderAccepted,
    ProviderFailure,
    ProviderOutcome,
)
from notification_service.domain.errors import ValidationError
from notification_service.domain.models import TeamsNotification
from notification_service.presentation.tables import (
    BoundedTable,
    TableRenderPolicy,
    bound_tables,
    reduce_largest_row_limit,
)

_WEBHOOK_PAYLOAD_LIMIT = 28_000


@dataclass(frozen=True, slots=True)
class PowerAutomateWebhook:
    """A deployment-owned Teams workflow webhook URL for one destination."""

    endpoint: str = field(repr=False)

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not parsed.query
            or len(self.endpoint) > 4096
            or any(ord(character) < 32 for character in self.endpoint)
        ):
            raise ValueError("Power Automate endpoint must be a signed HTTPS URL")


def _text_block(
    text: str,
    *,
    weight: str | None = None,
    size: str | None = None,
    spacing: str | None = None,
) -> dict[str, object]:
    block: dict[str, object] = {"type": "TextBlock", "text": text, "wrap": True}
    if weight is not None:
        block["weight"] = weight
    if size is not None:
        block["size"] = size
    if spacing is not None:
        block["spacing"] = spacing
    return block


def _column_set(values: tuple[str, ...], *, header: bool = False) -> dict[str, object]:
    return {
        "type": "ColumnSet",
        "spacing": "Small",
        "separator": header,
        "columns": [
            {
                "type": "Column",
                "width": "stretch",
                "items": [
                    _text_block(
                        value,
                        weight="Bolder" if header else None,
                    )
                ],
            }
            for value in values
        ],
    }


def _adaptive_card(
    notification: TeamsNotification,
    metadata: DeliveryMetadata,
    tables: tuple[BoundedTable, ...],
) -> dict[str, object]:
    body: list[dict[str, object]] = []
    if notification.title:
        body.append(_text_block(notification.title, weight="Bolder", size="Large"))
    body.append(_text_block(notification.text))
    body.append(
        {
            "type": "FactSet",
            "spacing": "Medium",
            "facts": [
                {"title": "Source", "value": metadata.source_application},
                {"title": "Correlation", "value": metadata.correlation_id},
            ],
        }
    )
    for table in tables:
        if table.caption:
            body.append(_text_block(table.caption, weight="Bolder", spacing="Medium"))
        body.append(_column_set(table.columns, header=True))
        body.extend(_column_set(row) for row in table.rows)
        omitted: list[str] = []
        if table.omitted_rows:
            omitted.append(f"{table.omitted_rows} row(s) omitted")
        if table.omitted_columns:
            omitted.append(f"{table.omitted_columns} column(s) omitted")
        if omitted:
            body.append(_text_block("Presentation summary: " + "; ".join(omitted)))
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": body,
                },
            }
        ],
    }


class PowerAutomateTeamsProvider:
    """Invoke a configured Teams workflow using an Adaptive Card webhook envelope."""

    def __init__(
        self,
        destinations: Mapping[str, PowerAutomateWebhook | str],
        *,
        client: httpx.AsyncClient | None = None,
        render_policy: TableRenderPolicy | None = None,
        throttling_proves_not_accepted: bool = False,
    ) -> None:
        if not destinations:
            raise ValueError("At least one Teams destination must be configured")
        configured = {
            name: value if isinstance(value, PowerAutomateWebhook) else PowerAutomateWebhook(value)
            for name, value in destinations.items()
        }
        self._destinations = configured
        self._render_policy = render_policy or TableRenderPolicy()
        self._throttling_proves_not_accepted = throttling_proves_not_accepted
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5, pool=5, read=30, write=30),
            follow_redirects=False,
            trust_env=True,
        )

    async def send(
        self,
        notification: TeamsNotification,
        metadata: DeliveryMetadata,
    ) -> ProviderOutcome:
        webhook = self._destinations.get(notification.destination)
        if webhook is None:
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.DESTINATION_NOT_CONFIGURED,
                diagnostic_code="power_automate_destination_missing",
            )
        try:
            payload = self._payload(notification, metadata)
        except ValidationError:
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.REQUEST_REJECTED,
                diagnostic_code="power_automate_payload_too_large",
            )
        try:
            response = await self._client.post(
                webhook.endpoint,
                json=payload,
                follow_redirects=False,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
                diagnostic_code="power_automate_connect_failed",
            )
        except (httpx.ReadError, httpx.ReadTimeout, httpx.WriteError, httpx.WriteTimeout):
            return ProviderFailure(
                certainty=AcceptanceCertainty.UNKNOWN,
                error_code=DeliveryErrorCode.DELIVERY_AMBIGUOUS,
                diagnostic_code="power_automate_response_lost",
            )
        except httpx.HTTPError:
            return ProviderFailure(
                certainty=AcceptanceCertainty.UNKNOWN,
                error_code=DeliveryErrorCode.PROVIDER_PROTOCOL_ERROR,
                diagnostic_code="power_automate_http_protocol",
            )

        if 200 <= response.status_code < 300:
            return ProviderAccepted(provider_message_id=self._message_id(response))
        if response.status_code == 429:
            if self._throttling_proves_not_accepted:
                return ProviderFailure(
                    certainty=AcceptanceCertainty.NOT_ACCEPTED,
                    error_code=DeliveryErrorCode.THROTTLED,
                    retryable=True,
                    retry_after_seconds=self._retry_after(response),
                    diagnostic_code="power_automate_http_429",
                )
            return ProviderFailure(
                certainty=AcceptanceCertainty.UNKNOWN,
                error_code=DeliveryErrorCode.THROTTLED,
                diagnostic_code="power_automate_http_429",
            )
        if response.status_code == 408 or response.status_code >= 500:
            return ProviderFailure(
                certainty=AcceptanceCertainty.UNKNOWN,
                error_code=DeliveryErrorCode.DELIVERY_AMBIGUOUS,
                diagnostic_code=f"power_automate_http_{response.status_code}",
            )
        error_code = (
            DeliveryErrorCode.AUTHENTICATION_FAILED
            if response.status_code in {401, 403}
            else DeliveryErrorCode.REQUEST_REJECTED
        )
        return ProviderFailure(
            certainty=AcceptanceCertainty.NOT_ACCEPTED,
            error_code=error_code,
            diagnostic_code=f"power_automate_http_{response.status_code}",
        )

    def _payload(
        self,
        notification: TeamsNotification,
        metadata: DeliveryMetadata,
    ) -> dict[str, object]:
        row_limits = [
            min(self._render_policy.max_rows, len(table.rows)) for table in notification.tables
        ]
        while True:
            tables = bound_tables(
                notification.tables,
                self._render_policy,
                row_limits=tuple(row_limits),
            )
            payload = _adaptive_card(notification, metadata, tables)
            payload_size = len(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            )
            if payload_size <= min(self._render_policy.teams_payload_bytes, _WEBHOOK_PAYLOAD_LIMIT):
                return payload
            if not reduce_largest_row_limit(row_limits):
                raise ValidationError(
                    "Teams content cannot fit within the configured payload limit"
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
                if isinstance(candidate, str) and 0 < len(candidate) <= 255:
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
                parsed_date: object = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return None
            if not isinstance(parsed_date, datetime) or parsed_date.tzinfo is None:
                return None
            return max(0.0, (parsed_date - datetime.now(UTC)).total_seconds())

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
