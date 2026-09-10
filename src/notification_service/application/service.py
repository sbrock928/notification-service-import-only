"""Transport-neutral orchestration called by an upstream worker."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from notification_service.application.ports import NotificationProvider
from notification_service.domain.errors import IdempotencyConflict, ProviderError, ValidationError
from notification_service.domain.models import (
    EmailNotification,
    Notification,
    ProviderAccepted,
    ProviderRejected,
)


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
    """Process-local duplicate protection for one client instance."""

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, DeliveryResult]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> tuple[str, DeliveryResult] | None:
        async with self._lock:
            return self._values.get(key)

    async def put(self, key: str, fingerprint: str, result: DeliveryResult) -> None:
        async with self._lock:
            self._values.setdefault(key, (fingerprint, result))


class NotificationClient[NotificationT: Notification]:
    """Apply common policy and delivery semantics to one provider."""

    def __init__(
        self,
        provider: NotificationProvider[NotificationT],
        *,
        idempotency: IdempotencyStore | None = None,
        max_attempts: int = 2,
        timeout_seconds: float = 120,
        allowed_email_domains: frozenset[str] = frozenset(),
        allowed_domains: frozenset[str] | None = None,
    ) -> None:
        if max_attempts < 1 or max_attempts > 2:
            raise ValueError("max_attempts must be 1 or 2")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if allowed_domains is not None and allowed_email_domains:
            raise ValueError("Use allowed_email_domains or allowed_domains, not both")
        configured_domains = (
            allowed_domains if allowed_domains is not None else allowed_email_domains
        )
        self.provider = provider
        self.idempotency = idempotency or InMemoryIdempotencyStore()
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.allowed_email_domains = frozenset(
            domain.lower().lstrip("@").rstrip(".") for domain in configured_domains
        )

    async def send(self, notification: NotificationT) -> DeliveryResult:
        """Send once, retrying only failures proven to precede acceptance."""
        self._validate_policy(notification)
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
                return await self._remember(
                    notification,
                    DeliveryResult(DeliveryState.UNKNOWN, attempts=attempt, error_code="timeout"),
                )
            except ProviderError as error:
                if error.retryable and attempt < self.max_attempts:
                    await asyncio.sleep(random.uniform(0.5, 1.5))
                    continue
                state = DeliveryState.UNKNOWN if error.accepted else DeliveryState.FAILED
                return await self._remember(
                    notification,
                    DeliveryResult(state, attempts=attempt, error_code=type(error).__name__),
                )

            if isinstance(outcome, ProviderAccepted):
                return await self._remember(
                    notification,
                    DeliveryResult(DeliveryState.ACCEPTED, outcome.provider_message_id, attempt),
                )
            if isinstance(outcome, ProviderRejected):
                if outcome.known_not_accepted and outcome.retryable and attempt < self.max_attempts:
                    await asyncio.sleep(outcome.retry_after_seconds or random.uniform(0.5, 1.5))
                    continue
                state = (
                    DeliveryState.FAILED if outcome.known_not_accepted else DeliveryState.UNKNOWN
                )
                return await self._remember(
                    notification,
                    DeliveryResult(state, attempts=attempt, error_code=outcome.code),
                )
        raise AssertionError("retry loop must return")

    def _validate_policy(self, notification: NotificationT) -> None:
        if not self.allowed_email_domains or not isinstance(notification, EmailNotification):
            return
        for recipient in notification.all_recipients:
            domain = recipient.address.rsplit("@", 1)[1].lower().rstrip(".")
            if domain not in self.allowed_email_domains:
                raise ValidationError("External recipients are prohibited by client policy")

    async def _remember(
        self, notification: NotificationT, result: DeliveryResult
    ) -> DeliveryResult:
        if notification.idempotency_key:
            await self.idempotency.put(
                notification.idempotency_key, notification.fingerprint, result
            )
        return result

    async def aclose(self) -> None:
        await self.provider.aclose()
