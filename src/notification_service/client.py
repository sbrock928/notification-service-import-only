"""Synchronous convenience facade over the async notification core."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from types import TracebackType
from typing import Any, Self, TypeVar

from notification_service.application.contracts import DeliveryResult
from notification_service.application.service import NotificationClient
from notification_service.domain.errors import ClientClosedError
from notification_service.domain.models import Notification

T = TypeVar("T")


class SyncNotificationClient[NotificationT: Notification]:
    """Own one async client and event loop on a private thread."""

    def __init__(self, factory: Callable[[], NotificationClient[NotificationT]]) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Use NotificationClient directly inside an active event loop")
        self._loop = asyncio.new_event_loop()
        self._closed = False
        self._thread = threading.Thread(
            target=self._run_loop,
            name="notification-sync-client",
            daemon=True,
        )
        self._thread.start()
        created: Future[NotificationClient[NotificationT]] = Future()

        def create() -> None:
            try:
                created.set_result(factory())
            except BaseException as error:
                created.set_exception(error)

        self._loop.call_soon_threadsafe(create)
        try:
            self._client = created.result()
        except BaseException:
            self._shutdown_loop()
            raise

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _call(self, coroutine: Coroutine[Any, Any, T]) -> T:
        if self._closed:
            coroutine.close()
            raise ClientClosedError("Notification client is closed")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result()

    def send(
        self,
        notification: NotificationT,
        *,
        idempotency_key: str | None = None,
        correlation_id: str | None = None,
    ) -> DeliveryResult:
        return self._call(
            self._client.send(
                notification,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
            )
        )

    def _shutdown_loop(self) -> None:
        self._closed = True
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._loop.close()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._call(self._client.aclose())
        finally:
            self._shutdown_loop()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
