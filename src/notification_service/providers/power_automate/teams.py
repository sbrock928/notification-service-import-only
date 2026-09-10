"""Teams delivery through named Power Automate HTTP-trigger flows."""

from __future__ import annotations

import json
import re
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

_HOST = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
)


@dataclass(frozen=True, slots=True)
class PowerAutomateWebhook:
    """A deployment-owned signed URL for one logical destination."""

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
        ):
            raise ValueError("Power Automate endpoint must be a signed HTTPS URL")


def _table_value(table: BoundedTable) -> dict[str, object]:
    return {
        "caption": table.caption,
        "columns": list(table.columns),
        "rows": [list(row) for row in table.rows],
        "omitted_row_count": table.omitted_rows,
        "omitted_column_count": table.omitted_columns,
    }


class PowerAutomateTeamsProvider:
    """Resolve a logical destination and invoke its preconfigured schema-v2 Flow."""

    def __init__(
        self,
        destinations: Mapping[str, PowerAutomateWebhook | str],
        *,
        allowed_host_suffixes: frozenset[str] | set[str],
        client: httpx.AsyncClient | None = None,
        render_policy: TableRenderPolicy | None = None,
        throttling_proves_not_accepted: bool = False,
    ) -> None:
        if not destinations:
            raise ValueError("At least one Teams destination must be configured")
        suffixes = frozenset(
            value.lower().lstrip(".").rstrip(".") for value in allowed_host_suffixes
        )
        if not suffixes or any(not _HOST.fullmatch(value) for value in suffixes):
            raise ValueError("Explicit canonical Power Automate host suffixes are required")
        configured = {
            name: value if isinstance(value, PowerAutomateWebhook) else PowerAutomateWebhook(value)
            for name, value in destinations.items()
        }
        for webhook in configured.values():
            hostname = urlparse(webhook.endpoint).hostname
            assert hostname is not None
            canonical = hostname.lower().rstrip(".")
            if not any(
                canonical == suffix or canonical.endswith("." + suffix) for suffix in suffixes
            ):
                raise ValueError("Power Automate endpoint host is not deployment-approved")
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
            payload: dict[str, object] = {
                "schema_version": 2,
                "correlation_id": metadata.correlation_id,
                "idempotency_key": metadata.idempotency_key,
                "source_application": metadata.source_application,
                "destination": notification.destination,
                "title": notification.title,
                "text": notification.text,
                "tables": [_table_value(table) for table in tables],
            }
            if (
                len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
                <= self._render_policy.teams_payload_bytes
            ):
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
