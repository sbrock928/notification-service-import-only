"""Small orchestration service intended to be called by an upstream worker."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from notification_service.errors import IdempotencyConflict, ProviderError, ValidationError
from notification_service.models import EmailNotification, ProviderAccepted, ProviderRejected
from notification_service.provider import EmailProvider


class DeliveryState(StrEnum):
    ACCEPTED = "accepted"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DeliveryResult:
    state: DeliveryState
    provider_message_id: str | None = None
    attempts: int = 1
    error_code: str | None = None


class IdempotencyStore(Protocol):
    async def get(self, key: str) -> tuple[str, DeliveryResult] | None: ...

    async def put(self, key: str, fingerprint: str, result: DeliveryResult) -> None: ...


class InMemoryIdempotencyStore:
    """Process-local duplicate protection; use a shared store in the calling application for restarts."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, DeliveryResult]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> tuple[str, DeliveryResult] | None:
        async with self._lock:
            return self._values.get(key)

    async def put(self, key: str, fingerprint: str, result: DeliveryResult) -> None:
        async with self._lock:
            self._values.setdefault(key, (fingerprint, result))


class NotificationClient:
    """Async import-only client. It performs no scheduling and owns no worker process."""

    def __init__(
        self,
        provider: EmailProvider,
        *,
        idempotency: IdempotencyStore | None = None,
        max_attempts: int = 2,
        timeout_seconds: float = 120,
        allowed_domains: frozenset[str] = frozenset(),
    ) -> None:
        if max_attempts < 1 or max_attempts > 2:
            raise ValueError("max_attempts must be 1 or 2")
        self.provider = provider
        self.idempotency = idempotency or InMemoryIdempotencyStore()
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.allowed_domains = frozenset(
            domain.lower().lstrip("@").rstrip(".") for domain in allowed_domains
        )

    async def send(self, notification: EmailNotification) -> DeliveryResult:
        """Send once, retrying only failures proven to precede provider acceptance."""
        if self.allowed_domains:
            for recipient in notification.all_recipients:
                domain = recipient.address.rsplit("@", 1)[1].lower().rstrip(".")
                if domain not in self.allowed_domains:
                    raise ValidationError("External recipients are prohibited by client policy")
        if notification.idempotency_key:
            previous = await self.idempotency.get(notification.idempotency_key)
            if previous:
                fingerprint, result = previous
                if fingerprint != notification.fingerprint:
                    raise IdempotencyConflict("Idempotency key was reused for different content")
                return result
        for attempt in range(1, self.max_attempts + 1):
            try:
                async with asyncio.timeout(self.timeout_seconds):
                    outcome = await self.provider.send(notification)
            except TimeoutError:
                result = DeliveryResult(
                    DeliveryState.UNKNOWN, attempts=attempt, error_code="timeout"
                )
                if notification.idempotency_key:
                    await self.idempotency.put(
                        notification.idempotency_key, notification.fingerprint, result
                    )
                return result
            except ProviderError as error:
                if not error.retryable or attempt == self.max_attempts:
                    state = DeliveryState.UNKNOWN if error.accepted else DeliveryState.FAILED
                    result = DeliveryResult(
                        state, attempts=attempt, error_code=type(error).__name__
                    )
                    if notification.idempotency_key:
                        await self.idempotency.put(
                            notification.idempotency_key, notification.fingerprint, result
                        )
                    return result
                await asyncio.sleep(random.uniform(0.5, 1.5))
                continue
            if isinstance(outcome, ProviderAccepted):
                result = DeliveryResult(
                    DeliveryState.ACCEPTED, outcome.provider_message_id, attempt
                )
                if notification.idempotency_key:
                    await self.idempotency.put(
                        notification.idempotency_key, notification.fingerprint, result
                    )
                return result
            if isinstance(outcome, ProviderRejected):
                if outcome.known_not_accepted and outcome.retryable and attempt < self.max_attempts:
                    await asyncio.sleep(outcome.retry_after_seconds or random.uniform(0.5, 1.5))
                    continue
                state = (
                    DeliveryState.FAILED if outcome.known_not_accepted else DeliveryState.UNKNOWN
                )
                result = DeliveryResult(state, attempts=attempt, error_code=outcome.code)
                if notification.idempotency_key:
                    await self.idempotency.put(
                        notification.idempotency_key, notification.fingerprint, result
                    )
                return result
        raise AssertionError("retry loop must return")

    async def aclose(self) -> None:
        await self.provider.aclose()
