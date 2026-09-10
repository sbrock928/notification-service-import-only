"""Atomic idempotency contracts and the process-local implementation."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from notification_service.application.contracts import (
    DeliveryErrorCode,
    DeliveryResult,
    DeliveryState,
)
from notification_service.domain.errors import IdempotencyConflict


@dataclass(frozen=True, slots=True)
class IdempotencyScope:
    source_application: str
    channel: str
    key: str


class ClaimStatus(StrEnum):
    ACQUIRED = "acquired"
    WAIT = "wait"
    REPLAY = "replay"


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    status: ClaimStatus
    scope: IdempotencyScope
    fingerprint: str
    token: str | None = None
    result: DeliveryResult | None = None
    waiter: asyncio.Event | None = None


class AtomicIdempotencyStore(Protocol):
    async def claim(
        self,
        scope: IdempotencyScope,
        fingerprint: str,
        correlation_id: str,
        lease_seconds: float,
    ) -> IdempotencyClaim: ...

    async def wait(
        self, claim: IdempotencyClaim, timeout_seconds: float
    ) -> DeliveryResult | None: ...

    async def complete(
        self,
        claim: IdempotencyClaim,
        result: DeliveryResult,
    ) -> None: ...

    async def release(self, claim: IdempotencyClaim) -> None: ...


@dataclass(slots=True)
class _Record:
    fingerprint: str
    correlation_id: str
    token: str
    lease_expires_at: float
    event: asyncio.Event
    result: DeliveryResult | None = None
    completed_at: float | None = None


class InMemoryIdempotencyStore:
    """Atomic process-local duplicate protection for one event loop."""

    def __init__(
        self,
        *,
        result_ttl_seconds: float = 24 * 60 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if result_ttl_seconds <= 0:
            raise ValueError("result_ttl_seconds must be positive")
        self._ttl = result_ttl_seconds
        self._clock = clock
        self._records: dict[IdempotencyScope, _Record] = {}
        self._lock = asyncio.Lock()

    async def claim(
        self,
        scope: IdempotencyScope,
        fingerprint: str,
        correlation_id: str,
        lease_seconds: float,
    ) -> IdempotencyClaim:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        async with self._lock:
            now = self._clock()
            record = self._records.get(scope)
            if record is not None and self._is_expired_final(record, now):
                del self._records[scope]
                record = None
            if record is not None and record.result is None and record.lease_expires_at <= now:
                record.result = DeliveryResult(
                    state=DeliveryState.UNKNOWN,
                    correlation_id=record.correlation_id,
                    attempts=0,
                    error_code=DeliveryErrorCode.DELIVERY_AMBIGUOUS,
                )
                record.completed_at = now
                record.event.set()
            if record is None:
                token = str(uuid4())
                record = _Record(
                    fingerprint=fingerprint,
                    correlation_id=correlation_id,
                    token=token,
                    lease_expires_at=now + lease_seconds,
                    event=asyncio.Event(),
                )
                self._records[scope] = record
                return IdempotencyClaim(ClaimStatus.ACQUIRED, scope, fingerprint, token=token)
            if record.fingerprint != fingerprint:
                raise IdempotencyConflict("Idempotency key was reused for different content")
            if record.result is not None:
                return IdempotencyClaim(
                    ClaimStatus.REPLAY,
                    scope,
                    fingerprint,
                    token=record.token,
                    result=record.result,
                )
            return IdempotencyClaim(
                ClaimStatus.WAIT,
                scope,
                fingerprint,
                token=record.token,
                waiter=record.event,
            )

    def _is_expired_final(self, record: _Record, now: float) -> bool:
        return (
            record.result is not None
            and record.result.state is not DeliveryState.UNKNOWN
            and record.completed_at is not None
            and record.completed_at + self._ttl <= now
        )

    async def wait(
        self,
        claim: IdempotencyClaim,
        timeout_seconds: float,
    ) -> DeliveryResult | None:
        if claim.waiter is None:
            return claim.result
        try:
            await asyncio.wait_for(claim.waiter.wait(), timeout=max(0.0, timeout_seconds))
        except TimeoutError:
            return None
        async with self._lock:
            record = self._records.get(claim.scope)
            if record is None or record.fingerprint != claim.fingerprint:
                return None
            return record.result

    async def complete(self, claim: IdempotencyClaim, result: DeliveryResult) -> None:
        async with self._lock:
            record = self._records.get(claim.scope)
            if (
                record is None
                or record.fingerprint != claim.fingerprint
                or record.token != claim.token
            ):
                return
            if record.result is not None and not (
                record.result.state is DeliveryState.UNKNOWN
                and result.state is not DeliveryState.UNKNOWN
            ):
                return
            record.result = replace(result, correlation_id=record.correlation_id)
            record.completed_at = self._clock()
            record.event.set()

    async def release(self, claim: IdempotencyClaim) -> None:
        async with self._lock:
            record = self._records.get(claim.scope)
            if (
                record is not None
                and record.result is None
                and record.fingerprint == claim.fingerprint
                and record.token == claim.token
            ):
                del self._records[claim.scope]
                record.event.set()

    async def resolve(
        self,
        *,
        source_application: str,
        channel: str,
        key: str,
        expected_fingerprint: str,
        result: DeliveryResult,
    ) -> None:
        """Resolve an unknown result without releasing its key for a resend."""
        if result.state is DeliveryState.UNKNOWN:
            raise ValueError("Operator resolution must be accepted or failed")
        scope = IdempotencyScope(source_application, channel, key)
        async with self._lock:
            record = self._records.get(scope)
            if record is None or record.fingerprint != expected_fingerprint:
                raise IdempotencyConflict("Unknown delivery does not match the supplied scope")
            if record.result is None or record.result.state is not DeliveryState.UNKNOWN:
                raise ValueError("Only unknown deliveries can be resolved")
            record.result = replace(result, correlation_id=record.correlation_id)
            record.completed_at = self._clock()
            record.event.set()
