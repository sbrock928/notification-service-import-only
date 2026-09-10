"""Transport-neutral orchestration for immediate notification delivery."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Self
from uuid import uuid4

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
    ClaimStatus,
    IdempotencyClaim,
    IdempotencyScope,
    InMemoryIdempotencyStore,
)
from notification_service.application.policies import NotificationPolicy
from notification_service.application.ports import NotificationProvider
from notification_service.application.retry import RetryPolicy
from notification_service.domain.errors import ClientClosedError, ProviderError, ValidationError
from notification_service.domain.models import Notification, TeamsNotification

_HEADER_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}")
_LOGGER = logging.getLogger("notification_service")


class NotificationClient[NotificationT: Notification]:
    """Apply common policy, idempotency, retry, and lifecycle semantics."""

    def __init__(
        self,
        provider: NotificationProvider[NotificationT],
        *,
        source_application: str,
        policies: tuple[NotificationPolicy, ...] = (),
        idempotency: AtomicIdempotencyStore | None = None,
        retry_policy: RetryPolicy | None = None,
        idempotency_lease_seconds: float = 150.0,
        close_drain_seconds: float = 30.0,
        random_source: Callable[[], float] = random.random,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not _HEADER_SAFE.fullmatch(source_application):
            raise ValueError("source_application must be a 1-128 character header-safe value")
        if idempotency_lease_seconds <= 0 or close_drain_seconds < 0:
            raise ValueError("lease and close-drain durations are invalid")
        self._provider = provider
        self._source_application = source_application
        self._policies = tuple(policies)
        self._idempotency = idempotency or InMemoryIdempotencyStore()
        self._retry = retry_policy or RetryPolicy()
        self._lease_seconds = idempotency_lease_seconds
        self._close_drain_seconds = close_drain_seconds
        self._random_source = random_source
        self._sleep = sleep
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._provider_tasks: set[asyncio.Task[ProviderOutcome]] = set()
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def send(
        self,
        notification: NotificationT,
        *,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> DeliveryResult:
        self._bind_loop()
        if self._closed:
            raise ClientClosedError("Notification client is closed")
        if idempotency_key is not None and not _HEADER_SAFE.fullmatch(idempotency_key):
            raise ValidationError(
                "Idempotency key must be a header-safe value up to 128 characters"
            )
        correlation_id = correlation_id or str(uuid4())
        if not _HEADER_SAFE.fullmatch(correlation_id):
            raise ValidationError("Correlation ID must be a header-safe value up to 128 characters")
        for policy in self._policies:
            policy.validate(notification)

        metadata = DeliveryMetadata(
            source_application=self._source_application,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            channel=notification.channel,
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._retry.total_timeout_seconds
        claim: IdempotencyClaim | None = None
        if idempotency_key is not None:
            scope = IdempotencyScope(
                self._source_application, notification.channel, idempotency_key
            )
            while True:
                claim = await self._idempotency.claim(
                    scope,
                    notification.fingerprint,
                    correlation_id,
                    self._lease_seconds,
                )
                if claim.status is ClaimStatus.REPLAY:
                    assert claim.result is not None
                    self._log(notification, claim.result, 0, "replay", None)
                    return claim.result
                if claim.status is ClaimStatus.ACQUIRED:
                    break
                result = await self._idempotency.wait(claim, max(0.0, deadline - loop.time()))
                if result is not None:
                    self._log(notification, result, 0, "wait_replay", None)
                    return result
                if loop.time() < deadline:
                    continue
                return DeliveryResult(
                    state=DeliveryState.UNKNOWN,
                    correlation_id=correlation_id,
                    attempts=0,
                    error_code=DeliveryErrorCode.IN_PROGRESS_TIMEOUT,
                )

        return await self._deliver(notification, metadata, claim, deadline)

    async def _deliver(
        self,
        notification: NotificationT,
        metadata: DeliveryMetadata,
        claim: IdempotencyClaim | None,
        deadline: float,
    ) -> DeliveryResult:
        loop = asyncio.get_running_loop()
        for attempt in range(1, self._retry.max_attempts + 1):
            remaining = deadline - loop.time()
            if remaining <= 0:
                result = DeliveryResult(
                    state=DeliveryState.UNKNOWN,
                    correlation_id=metadata.correlation_id,
                    attempts=attempt - 1,
                    error_code=DeliveryErrorCode.PROVIDER_TIMEOUT,
                )
                await self._complete(claim, result)
                return result

            started = loop.time()
            task = asyncio.create_task(self._invoke_provider(notification, metadata))
            self._provider_tasks.add(task)
            task.add_done_callback(self._provider_tasks.discard)
            try:
                done, _ = await asyncio.wait({task}, timeout=remaining)
            except asyncio.CancelledError:
                result = DeliveryResult(
                    state=DeliveryState.UNKNOWN,
                    correlation_id=metadata.correlation_id,
                    attempts=attempt,
                    error_code=DeliveryErrorCode.CANCELLED,
                )
                await self._complete(claim, result)
                self._track_late(task, claim, metadata.correlation_id, attempt)
                raise
            if not done:
                result = DeliveryResult(
                    state=DeliveryState.UNKNOWN,
                    correlation_id=metadata.correlation_id,
                    attempts=attempt,
                    error_code=DeliveryErrorCode.PROVIDER_TIMEOUT,
                )
                await self._complete(claim, result)
                self._track_late(task, claim, metadata.correlation_id, attempt)
                self._log(notification, result, loop.time() - started, "claimed", None)
                return result

            outcome = task.result()
            if isinstance(outcome, ProviderAccepted):
                result = DeliveryResult(
                    state=DeliveryState.ACCEPTED,
                    correlation_id=metadata.correlation_id,
                    provider_message_id=outcome.provider_message_id,
                    attempts=attempt,
                )
                await self._complete(claim, result)
                self._log(notification, result, loop.time() - started, "claimed", None)
                return result

            if (
                outcome.certainty is AcceptanceCertainty.NOT_ACCEPTED
                and outcome.retryable
                and attempt < self._retry.max_attempts
            ):
                delay = self._retry.delay(
                    attempt,
                    self._random_source(),
                    outcome.retry_after_seconds,
                )
                remaining = deadline - loop.time()
                if delay < remaining:
                    try:
                        await self._sleep(delay)
                    except asyncio.CancelledError:
                        result = self._failure_result(outcome, metadata.correlation_id, attempt)
                        await self._complete(claim, result)
                        raise
                    continue

            result = self._failure_result(outcome, metadata.correlation_id, attempt)
            await self._complete(claim, result)
            self._log(
                notification,
                result,
                loop.time() - started,
                "claimed",
                outcome.diagnostic_code,
            )
            return result
        raise AssertionError("retry loop must return")

    async def _invoke_provider(
        self,
        notification: NotificationT,
        metadata: DeliveryMetadata,
    ) -> ProviderOutcome:
        try:
            return await self._provider.send(notification, metadata)
        except ProviderError as error:
            return ProviderFailure(
                certainty=(
                    AcceptanceCertainty.UNKNOWN
                    if error.accepted
                    else AcceptanceCertainty.NOT_ACCEPTED
                ),
                error_code=DeliveryErrorCode.PROVIDER_PROTOCOL_ERROR,
                retryable=error.retryable and not error.accepted,
                diagnostic_code="legacy_provider_exception",
            )
        except Exception:
            return ProviderFailure(
                certainty=AcceptanceCertainty.UNKNOWN,
                error_code=DeliveryErrorCode.PROVIDER_PROTOCOL_ERROR,
                diagnostic_code="unhandled_provider_exception",
            )

    @staticmethod
    def _failure_result(
        outcome: ProviderFailure,
        correlation_id: str,
        attempts: int,
    ) -> DeliveryResult:
        state = (
            DeliveryState.FAILED
            if outcome.certainty is AcceptanceCertainty.NOT_ACCEPTED
            else DeliveryState.UNKNOWN
        )
        return DeliveryResult(
            state=state,
            correlation_id=correlation_id,
            attempts=attempts,
            error_code=outcome.error_code,
        )

    async def _complete(
        self,
        claim: IdempotencyClaim | None,
        result: DeliveryResult,
    ) -> None:
        if claim is not None:
            await self._idempotency.complete(claim, result)

    def _track_late(
        self,
        provider_task: asyncio.Task[ProviderOutcome],
        claim: IdempotencyClaim | None,
        correlation_id: str,
        attempts: int,
    ) -> None:
        async def refine() -> None:
            outcome = await asyncio.shield(provider_task)
            if claim is None:
                return
            if isinstance(outcome, ProviderAccepted):
                result = DeliveryResult(
                    state=DeliveryState.ACCEPTED,
                    correlation_id=correlation_id,
                    provider_message_id=outcome.provider_message_id,
                    attempts=attempts,
                )
            elif outcome.certainty is AcceptanceCertainty.NOT_ACCEPTED:
                result = self._failure_result(outcome, correlation_id, attempts)
            else:
                return
            await self._idempotency.complete(claim, result)

        task = asyncio.create_task(refine())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _bind_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise RuntimeError("NotificationClient cannot be shared across event loops")

    def _log(
        self,
        notification: NotificationT,
        result: DeliveryResult,
        duration: float,
        idempotency_status: str,
        diagnostic_code: str | None,
    ) -> None:
        destination = (
            notification.destination if isinstance(notification, TeamsNotification) else "email"
        )
        _LOGGER.info(
            "notification delivery completed",
            extra={
                "correlation_id": result.correlation_id,
                "source_application": self._source_application,
                "channel": notification.channel,
                "logical_destination": destination,
                "provider": type(self._provider).__name__,
                "attempt": result.attempts,
                "duration_seconds": duration,
                "delivery_state": result.state.value,
                "delivery_error_code": result.error_code.value if result.error_code else None,
                "diagnostic_code": diagnostic_code,
                "idempotency_status": idempotency_status,
            },
        )

    async def aclose(self) -> None:
        self._bind_loop()
        if self._closed:
            return
        self._closed = True
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._close_drain_seconds
        tracked = set(self._provider_tasks) | set(self._background_tasks)
        if tracked and self._close_drain_seconds:
            await asyncio.wait(tracked, timeout=self._close_drain_seconds)
        remaining = max(0.0, deadline - loop.time())
        close_task = asyncio.create_task(self._provider.aclose())
        if remaining:
            done, _ = await asyncio.wait({close_task}, timeout=remaining)
            if not done:
                self._background_tasks.add(close_task)
                close_task.add_done_callback(self._background_tasks.discard)
        else:
            self._background_tasks.add(close_task)
            close_task.add_done_callback(self._background_tasks.discard)

    async def __aenter__(self) -> Self:
        self._bind_loop()
        if self._closed:
            raise ClientClosedError("Notification client is closed")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()
