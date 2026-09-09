"""Ergonomic async and synchronous import-only facades."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable, Coroutine
from types import TracebackType
from typing import Any, Self, TypeVar

from notification_service.models import EmailNotification
from notification_service.service import DeliveryResult, NotificationClient

T = TypeVar("T")


class SyncNotificationClient:
    """Run one async client on a private loop thread for synchronous callers."""

    def __init__(self, factory: Callable[[], Awaitable[NotificationClient]]) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Use NotificationClient directly inside an active event loop")
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._closed = False

        async def create() -> NotificationClient:
            return await factory()

        self._client: NotificationClient = self._call(create())

    def _call(self, coroutine: Coroutine[Any, Any, T]) -> T:
        if self._closed:
            coroutine.close()
            raise RuntimeError("Client is closed")
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result()

    def send(self, notification: EmailNotification) -> DeliveryResult:
        return self._call(self._client.send(notification))

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._call(self._client.aclose())
        finally:
            self._closed = True
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()
            self._loop.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
