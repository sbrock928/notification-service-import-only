from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable

import pytest

from notification_service import (
    ClientClosedError,
    DeliveryErrorCode,
    DeliveryState,
    EmailNotification,
    IdempotencyConflict,
    InMemoryIdempotencyStore,
    NotificationClient,
    Recipient,
    RetryPolicy,
    SyncNotificationClient,
)
from notification_service.application import (
    AcceptanceCertainty,
    DeliveryMetadata,
    DeliveryResult,
    ProviderAccepted,
    ProviderFailure,
    ProviderOutcome,
)
from notification_service.application.idempotency import (
    ClaimStatus,
    IdempotencyScope,
)
from notification_service.domain.errors import ProviderError


def message(subject: str = "Ready") -> EmailNotification:
    return EmailNotification(to=(Recipient("ops@contoso.com"),), subject=subject, text="Done")


class FakeProvider:
    def __init__(
        self,
        outcomes: list[ProviderOutcome] | None = None,
        behavior: Callable[[], Awaitable[ProviderOutcome]] | None = None,
    ) -> None:
        self.outcomes = outcomes or []
        self.behavior = behavior
        self.calls = 0
        self.metadata: list[DeliveryMetadata] = []
        self.closed = False

    async def send(
        self,
        notification: EmailNotification,
        metadata: DeliveryMetadata,
    ) -> ProviderOutcome:
        self.calls += 1
        self.metadata.append(metadata)
        if self.behavior is not None:
            return await self.behavior()
        return (
            self.outcomes.pop(0) if self.outcomes else ProviderAccepted(provider_message_id="fake")
        )

    async def aclose(self) -> None:
        self.closed = True


async def no_sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_acceptance_metadata_and_idempotent_replay() -> None:
    provider = FakeProvider([ProviderAccepted(provider_message_id="msg-1")])
    client = NotificationClient(provider, source_application="worker")
    first = await client.send(message(), idempotency_key="job-1", correlation_id="corr-1")
    second = await client.send(message(), idempotency_key="job-1", correlation_id="corr-2")

    assert first == second
    assert first.state is DeliveryState.ACCEPTED
    assert first.correlation_id == "corr-1"
    assert provider.calls == 1
    assert provider.metadata[0].source_application == "worker"


@pytest.mark.asyncio
async def test_atomic_same_request_waits_and_different_request_conflicts() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def behavior() -> ProviderOutcome:
        entered.set()
        await release.wait()
        return ProviderAccepted(provider_message_id="once")

    provider = FakeProvider(behavior=behavior)
    client = NotificationClient(provider, source_application="worker")
    first = asyncio.create_task(client.send(message(), idempotency_key="job"))
    await entered.wait()
    second = asyncio.create_task(client.send(message(), idempotency_key="job"))
    with pytest.raises(IdempotencyConflict):
        await client.send(message("changed"), idempotency_key="job")
    release.set()
    left, right = await asyncio.gather(first, second)
    assert left == right
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_wait_budget_exhaustion_never_sends_twice() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def behavior() -> ProviderOutcome:
        entered.set()
        await release.wait()
        return ProviderAccepted()

    provider = FakeProvider(behavior=behavior)
    client = NotificationClient(
        provider,
        source_application="worker",
        retry_policy=RetryPolicy(total_timeout_seconds=0.01),
    )
    first = asyncio.create_task(client.send(message(), idempotency_key="job"))
    await entered.wait()
    second = await client.send(message(), idempotency_key="job")
    assert second.state is DeliveryState.UNKNOWN
    assert second.error_code is DeliveryErrorCode.IN_PROGRESS_TIMEOUT
    assert provider.calls == 1
    release.set()
    await first


@pytest.mark.asyncio
async def test_retry_only_proven_non_acceptance() -> None:
    provider = FakeProvider(
        [
            ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
            ),
            ProviderAccepted(provider_message_id="msg-2"),
        ]
    )
    result = await NotificationClient(
        provider,
        source_application="worker",
        sleep=no_sleep,
        random_source=lambda: 0.0,
    ).send(message())
    assert result.state is DeliveryState.ACCEPTED
    assert result.attempts == 2

    unknown = FakeProvider(
        [
            ProviderFailure(
                certainty=AcceptanceCertainty.UNKNOWN,
                error_code=DeliveryErrorCode.DELIVERY_AMBIGUOUS,
            )
        ]
    )
    result = await NotificationClient(unknown, source_application="worker").send(message())
    assert result.state is DeliveryState.UNKNOWN
    assert unknown.calls == 1


@pytest.mark.asyncio
async def test_timeout_is_unknown_and_late_acceptance_refines_store() -> None:
    release = asyncio.Event()

    async def behavior() -> ProviderOutcome:
        await release.wait()
        return ProviderAccepted(provider_message_id="late")

    provider = FakeProvider(behavior=behavior)
    client = NotificationClient(
        provider,
        source_application="worker",
        retry_policy=RetryPolicy(total_timeout_seconds=0.01),
    )
    timed_out = await client.send(message(), idempotency_key="job", correlation_id="original")
    assert timed_out.error_code is DeliveryErrorCode.PROVIDER_TIMEOUT
    release.set()
    for _ in range(10):
        await asyncio.sleep(0)
        replay = await client.send(message(), idempotency_key="job", correlation_id="new")
        if replay.state is DeliveryState.ACCEPTED:
            break
    assert replay.state is DeliveryState.ACCEPTED
    assert replay.correlation_id == "original"


@pytest.mark.asyncio
async def test_cancellation_after_invocation_is_recorded_and_reraised() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()

    async def behavior() -> ProviderOutcome:
        entered.set()
        await release.wait()
        return ProviderAccepted()

    client = NotificationClient(FakeProvider(behavior=behavior), source_application="worker")
    task = asyncio.create_task(client.send(message(), idempotency_key="cancelled"))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_lifecycle_loop_ownership_and_closed_state() -> None:
    provider = FakeProvider()
    client = NotificationClient(provider, source_application="worker")
    async with client:
        assert (await client.send(message())).state is DeliveryState.ACCEPTED
    assert provider.closed
    with pytest.raises(ClientClosedError):
        await client.send(message())


def test_sync_facade_builds_on_loop_thread_and_cleans_up() -> None:
    factory_thread: list[int] = []
    provider = FakeProvider()

    def factory() -> NotificationClient[EmailNotification]:
        factory_thread.append(threading.get_ident())
        return NotificationClient(provider, source_application="sync-worker")

    with SyncNotificationClient(factory) as client:
        result = client.send(message(), correlation_id="sync-corr")
        assert result.correlation_id == "sync-corr"
    assert factory_thread != [threading.get_ident()]
    assert provider.closed


def test_sync_factory_failure_does_not_leave_thread() -> None:
    before = {thread.ident for thread in threading.enumerate()}
    with pytest.raises(RuntimeError, match="factory"):
        SyncNotificationClient(lambda: (_ for _ in ()).throw(RuntimeError("factory")))
    after = {thread.ident for thread in threading.enumerate()}
    assert after == before


@pytest.mark.asyncio
async def test_operator_can_resolve_unknown() -> None:
    store = InMemoryIdempotencyStore()
    provider = FakeProvider(
        [
            ProviderFailure(
                certainty=AcceptanceCertainty.UNKNOWN,
                error_code=DeliveryErrorCode.DELIVERY_AMBIGUOUS,
            )
        ]
    )
    client = NotificationClient(provider, source_application="worker", idempotency=store)
    notification = message()
    original = await client.send(notification, idempotency_key="job", correlation_id="corr")
    assert original.state is DeliveryState.UNKNOWN
    await store.resolve(
        source_application="worker",
        channel="email",
        key="job",
        expected_fingerprint=notification.fingerprint,
        result=DeliveryResult(
            state=DeliveryState.FAILED,
            correlation_id="corr",
            error_code=DeliveryErrorCode.REQUEST_REJECTED,
        ),
    )
    assert (await client.send(notification, idempotency_key="job")).state is DeliveryState.FAILED


def test_retry_and_provider_failure_configuration_guards() -> None:
    for arguments in (
        {"max_attempts": 0},
        {"total_timeout_seconds": 0},
        {"base_delay_seconds": -1},
        {"max_retry_after_seconds": -1},
    ):
        with pytest.raises(ValueError):
            RetryPolicy(**arguments)  # type: ignore[arg-type]
    policy = RetryPolicy(max_retry_after_seconds=10)
    assert policy.delay(2, 0.5, None) == 0.5
    assert policy.delay(2, 0.5, 30) == 10
    with pytest.raises(ValueError, match="proven"):
        ProviderFailure(
            certainty=AcceptanceCertainty.UNKNOWN,
            error_code=DeliveryErrorCode.THROTTLED,
            retryable=True,
        )
    with pytest.raises(ValueError, match="negative"):
        ProviderFailure(
            certainty=AcceptanceCertainty.NOT_ACCEPTED,
            error_code=DeliveryErrorCode.THROTTLED,
            retry_after_seconds=-1,
        )


@pytest.mark.asyncio
async def test_idempotency_ttl_lease_release_and_resolution_guards() -> None:
    now = [10.0]
    store = InMemoryIdempotencyStore(result_ttl_seconds=5, clock=lambda: now[0])
    scope = IdempotencyScope("worker", "email", "job")
    first = await store.claim(scope, "fingerprint", "corr", 2)
    assert first.status is ClaimStatus.ACQUIRED
    waiting = await store.claim(scope, "fingerprint", "other", 2)
    assert waiting.status is ClaimStatus.WAIT
    assert await store.wait(waiting, 0) is None
    await store.release(first)
    second = await store.claim(scope, "fingerprint", "corr-2", 2)
    await store.complete(
        second,
        DeliveryResult(state=DeliveryState.FAILED, correlation_id="corr-2"),
    )
    assert (await store.claim(scope, "fingerprint", "x", 2)).status is ClaimStatus.REPLAY
    now[0] += 6
    assert (await store.claim(scope, "fingerprint", "corr-3", 2)).status is ClaimStatus.ACQUIRED

    lease_scope = IdempotencyScope("worker", "email", "lease")
    await store.claim(lease_scope, "fp", "lease-corr", 1)
    now[0] += 2
    expired = await store.claim(lease_scope, "fp", "new", 1)
    assert expired.result is not None
    assert expired.result.state is DeliveryState.UNKNOWN
    with pytest.raises(ValueError, match="accepted or failed"):
        await store.resolve(
            source_application="worker",
            channel="email",
            key="lease",
            expected_fingerprint="fp",
            result=expired.result,
        )
    with pytest.raises(IdempotencyConflict):
        await store.resolve(
            source_application="worker",
            channel="email",
            key="lease",
            expected_fingerprint="wrong",
            result=DeliveryResult(state=DeliveryState.FAILED, correlation_id="lease-corr"),
        )


@pytest.mark.asyncio
async def test_client_configuration_and_delivery_metadata_validation() -> None:
    with pytest.raises(ValueError, match="source_application"):
        NotificationClient(FakeProvider(), source_application="bad source")
    with pytest.raises(ValueError, match="durations"):
        NotificationClient(FakeProvider(), source_application="worker", close_drain_seconds=-1)
    client = NotificationClient(FakeProvider(), source_application="worker")
    with pytest.raises(Exception, match="Idempotency"):
        await client.send(message(), idempotency_key="bad key")
    with pytest.raises(Exception, match="Correlation"):
        await client.send(message(), correlation_id="bad correlation")


@pytest.mark.asyncio
async def test_provider_exceptions_are_normalized() -> None:
    class Raising(FakeProvider):
        def __init__(self, error: Exception) -> None:
            super().__init__()
            self.error = error

        async def send(
            self, notification: EmailNotification, metadata: DeliveryMetadata
        ) -> ProviderOutcome:
            raise self.error

    legacy = NotificationClient(
        Raising(ProviderError("busy", retryable=False)), source_application="worker"
    )
    assert (await legacy.send(message())).state is DeliveryState.FAILED
    broken = NotificationClient(Raising(RuntimeError("boom")), source_application="worker")
    result = await broken.send(message())
    assert result.state is DeliveryState.UNKNOWN
    assert result.error_code is DeliveryErrorCode.PROVIDER_PROTOCOL_ERROR


@pytest.mark.asyncio
async def test_cancellation_during_retry_delay_stores_known_failure() -> None:
    sleeping = asyncio.Event()

    async def wait_forever(_: float) -> None:
        sleeping.set()
        await asyncio.Event().wait()

    provider = FakeProvider(
        [
            ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.PROVIDER_UNAVAILABLE,
                retryable=True,
            )
        ]
    )
    client = NotificationClient(provider, source_application="worker", sleep=wait_forever)
    task = asyncio.create_task(client.send(message(), idempotency_key="retry-cancel"))
    await sleeping.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    replay = await client.send(message(), idempotency_key="retry-cancel")
    assert replay.state is DeliveryState.FAILED


@pytest.mark.asyncio
async def test_sync_facade_is_rejected_inside_running_loop() -> None:
    with pytest.raises(RuntimeError, match="active event loop"):
        SyncNotificationClient(
            lambda: NotificationClient(FakeProvider(), source_application="worker")
        )
