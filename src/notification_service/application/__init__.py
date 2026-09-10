"""Transport-neutral notification orchestration."""

from notification_service.application.contracts import (
    AcceptanceCertainty,
    DeliveryErrorCode,
    DeliveryMetadata,
    DeliveryResult,
    DeliveryState,
    ProviderAccepted,
    ProviderFailure,
    ProviderOutcome,
)
from notification_service.application.idempotency import (
    AtomicIdempotencyStore,
    IdempotencyClaim,
    IdempotencyScope,
    InMemoryIdempotencyStore,
)
from notification_service.application.policies import AllowedEmailDomainsPolicy, NotificationPolicy
from notification_service.application.ports import NotificationProvider
from notification_service.application.retry import RetryPolicy
from notification_service.application.service import NotificationClient

__all__ = [
    "AcceptanceCertainty",
    "AllowedEmailDomainsPolicy",
    "AtomicIdempotencyStore",
    "DeliveryErrorCode",
    "DeliveryMetadata",
    "DeliveryResult",
    "DeliveryState",
    "IdempotencyClaim",
    "IdempotencyScope",
    "InMemoryIdempotencyStore",
    "NotificationClient",
    "NotificationPolicy",
    "NotificationProvider",
    "ProviderAccepted",
    "ProviderFailure",
    "ProviderOutcome",
    "RetryPolicy",
]
