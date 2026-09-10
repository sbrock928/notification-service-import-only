"""Email delivery through the locally configured Outlook desktop client."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from notification_service.domain.models import (
    EmailNotification,
    ProviderAccepted,
    ProviderOutcome,
    ProviderRejected,
)


class OutlookAttachments(Protocol):
    def Add(self, path: str) -> object: ...


class OutlookMailItem(Protocol):
    To: str
    CC: str
    BCC: str
    Subject: str
    Body: str
    HTMLBody: str
    SentOnBehalfOfName: str
    Attachments: OutlookAttachments

    def Send(self) -> None: ...


class OutlookApplication(Protocol):
    def CreateItem(self, item_type: int) -> OutlookMailItem: ...


class Win32OutlookEmailProvider:
    """Use Outlook's current Windows profile without leaking COM objects."""

    def __init__(
        self,
        *,
        sender: str | None = None,
        application_factory: Callable[[], OutlookApplication] | None = None,
    ) -> None:
        self._sender = sender
        self._application_factory = application_factory
        self._lock = asyncio.Lock()

    async def send(self, notification: EmailNotification) -> ProviderOutcome:
        async with self._lock:
            return await asyncio.to_thread(self._send_sync, notification)

    def _send_sync(self, notification: EmailNotification) -> ProviderOutcome:
        if self._application_factory is not None:
            return self._compose_and_send(self._application_factory(), notification)
        if sys.platform != "win32":
            return ProviderRejected(
                "win32com_unavailable",
                "The win32com Outlook provider requires Windows",
                False,
            )

        try:
            import pythoncom
            import win32com.client
        except ImportError:
            return ProviderRejected(
                "win32com_unavailable",
                "Install the outlook-win32 package extra on Windows",
                False,
            )

        pythoncom.CoInitialize()
        try:
            application = win32com.client.Dispatch("Outlook.Application")
            return self._compose_and_send(application, notification)
        finally:
            pythoncom.CoUninitialize()

    def _compose_and_send(
        self, application: OutlookApplication, notification: EmailNotification
    ) -> ProviderOutcome:
        send_invoked = False
        try:
            message = application.CreateItem(0)
            message.To = ";".join(recipient.address for recipient in notification.to)
            message.CC = ";".join(recipient.address for recipient in notification.cc)
            message.BCC = ";".join(recipient.address for recipient in notification.bcc)
            message.Subject = notification.subject
            if notification.html is not None:
                message.HTMLBody = notification.html
            else:
                message.Body = notification.text
            if self._sender:
                message.SentOnBehalfOfName = self._sender

            with TemporaryDirectory(prefix="notification-attachments-") as directory:
                for index, attachment in enumerate(notification.attachments):
                    path = Path(directory, f"{index:02d}-{attachment.filename}")
                    path.write_bytes(attachment.content)
                    message.Attachments.Add(str(path))
                send_invoked = True
                message.Send()
            return ProviderAccepted(None)
        except Exception:
            return ProviderRejected(
                "outlook_com_error",
                "Outlook could not complete the send operation",
                not send_invoked,
                not send_invoked,
            )

    async def aclose(self) -> None:
        """The adapter creates and releases COM objects for each operation."""
