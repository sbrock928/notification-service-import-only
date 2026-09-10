"""Advanced application contracts shared by orchestration and adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeliveryState(StrEnum):
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNKNOWN = "unknown"


class DeliveryErrorCode(StrEnum):
    DESTINATION_NOT_CONFIGURED = "destination_not_configured"
    SENDER_NOT_AVAILABLE = "sender_not_available"
    AUTHENTICATION_FAILED = "authentication_failed"
    REQUEST_REJECTED = "request_rejected"
    THROTTLED = "throttled"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    INVALID_PROVIDER_RESPONSE = "invalid_provider_response"
    PROVIDER_PROTOCOL_ERROR = "provider_protocol_error"
    DELIVERY_AMBIGUOUS = "delivery_ambiguous"
    IN_PROGRESS_TIMEOUT = "in_progress_timeout"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliveryResult:
    state: DeliveryState
    correlation_id: str
    provider_message_id: str | None = None
    attempts: int = 1
    error_code: DeliveryErrorCode | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class DeliveryMetadata:
    source_application: str
    correlation_id: str
    idempotency_key: str | None
    channel: str


class AcceptanceCertainty(StrEnum):
    NOT_ACCEPTED = "not_accepted"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderAccepted:
    provider_message_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ProviderFailure:
    certainty: AcceptanceCertainty
    error_code: DeliveryErrorCode
    retryable: bool = False
    retry_after_seconds: float | None = None
    diagnostic_code: str | None = None

    def __post_init__(self) -> None:
        if self.retryable and self.certainty is not AcceptanceCertainty.NOT_ACCEPTED:
            raise ValueError("Only proven non-acceptance can be retryable")
        if self.retry_after_seconds is not None and self.retry_after_seconds < 0:
            raise ValueError("Retry-After cannot be negative")


ProviderOutcome = ProviderAccepted | ProviderFailure
