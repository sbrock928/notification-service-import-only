"""Email delivery through a classic Outlook profile on one serial COM worker."""

from __future__ import annotations

import asyncio
import os
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from notification_service.application.contracts import (
    AcceptanceCertainty,
    DeliveryErrorCode,
    DeliveryMetadata,
    ProviderAccepted,
    ProviderFailure,
    ProviderOutcome,
)
from notification_service.domain.models import EmailNotification
from notification_service.presentation.email import render_email
from notification_service.presentation.tables import TableRenderPolicy


class OutlookAccount(Protocol):
    SmtpAddress: str


class OutlookAccounts(Protocol):
    Count: int

    def Item(self, index: int) -> OutlookAccount: ...


class OutlookSession(Protocol):
    Accounts: OutlookAccounts


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
    SendUsingAccount: OutlookAccount
    Attachments: OutlookAttachments

    def Send(self) -> None: ...


class OutlookApplication(Protocol):
    Session: OutlookSession

    def CreateItem(self, item_type: int) -> OutlookMailItem: ...


class Win32OutlookEmailProvider:
    """Send through one fixed account in the signed-in classic Outlook profile."""

    def __init__(
        self,
        *,
        account_address: str,
        send_as_address: str | None = None,
        application_factory: Callable[[], OutlookApplication] | None = None,
        render_policy: TableRenderPolicy | None = None,
    ) -> None:
        if not account_address or "\r" in account_address or "\n" in account_address:
            raise ValueError("account_address is required")
        if send_as_address is not None and (
            not send_as_address or "\r" in send_as_address or "\n" in send_as_address
        ):
            raise ValueError("send_as_address is invalid")
        self._account_address = account_address.casefold()
        self._send_as_address = send_as_address
        self._application_factory = application_factory
        self._render_policy = render_policy or TableRenderPolicy()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="notification-outlook"
        )
        self._closed = False

    async def send(
        self,
        notification: EmailNotification,
        metadata: DeliveryMetadata,
    ) -> ProviderOutcome:
        del metadata
        if self._closed:
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.PROVIDER_UNAVAILABLE,
                diagnostic_code="outlook_provider_closed",
            )
        rendered = render_email(notification, self._render_policy)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self._send_sync,
            notification,
            rendered.text,
            rendered.html,
        )

    def _send_sync(
        self,
        notification: EmailNotification,
        rendered_text: str,
        rendered_html: str | None,
    ) -> ProviderOutcome:
        if self._application_factory is not None:
            try:
                return self._compose_and_send(
                    self._application_factory(), notification, rendered_text, rendered_html
                )
            except Exception:
                return ProviderFailure(
                    certainty=AcceptanceCertainty.NOT_ACCEPTED,
                    error_code=DeliveryErrorCode.PROVIDER_UNAVAILABLE,
                    diagnostic_code="outlook_start_failed",
                )
        if sys.platform != "win32":
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.PROVIDER_UNAVAILABLE,
                diagnostic_code="win32com_unavailable",
            )
        try:
            import pythoncom
            import win32com.client
        except ImportError:
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.PROVIDER_UNAVAILABLE,
                diagnostic_code="win32com_unavailable",
            )

        pythoncom.CoInitialize()
        try:
            application = win32com.client.Dispatch("Outlook.Application")
            return self._compose_and_send(application, notification, rendered_text, rendered_html)
        except Exception:
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.PROVIDER_UNAVAILABLE,
                diagnostic_code="outlook_start_failed",
            )
        finally:
            pythoncom.CoUninitialize()

    def _compose_and_send(
        self,
        application: OutlookApplication,
        notification: EmailNotification,
        rendered_text: str,
        rendered_html: str | None,
    ) -> ProviderOutcome:
        try:
            account = self._find_account(application.Session.Accounts)
        except Exception:
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.SENDER_NOT_AVAILABLE,
                diagnostic_code="outlook_account_lookup_failed",
            )
        if account is None:
            return ProviderFailure(
                certainty=AcceptanceCertainty.NOT_ACCEPTED,
                error_code=DeliveryErrorCode.SENDER_NOT_AVAILABLE,
                diagnostic_code="outlook_account_missing",
            )

        send_invoked = False
        try:
            message = application.CreateItem(0)
            message.SendUsingAccount = account
            message.To = ";".join(recipient.address for recipient in notification.to)
            message.CC = ";".join(recipient.address for recipient in notification.cc)
            message.BCC = ";".join(recipient.address for recipient in notification.bcc)
            message.Subject = notification.subject
            message.Body = rendered_text
            if rendered_html is not None:
                message.HTMLBody = rendered_html
            if self._send_as_address is not None:
                message.SentOnBehalfOfName = self._send_as_address

            with TemporaryDirectory(prefix="notification-attachments-") as directory:
                for index, attachment in enumerate(notification.attachments):
                    path = Path(directory, f"{index:02d}-{attachment.filename}")
                    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    try:
                        with os.fdopen(descriptor, "wb") as stream:
                            stream.write(attachment.content)
                    except BaseException:
                        try:
                            os.close(descriptor)
                        except OSError:
                            pass
                        raise
                    message.Attachments.Add(str(path))
                send_invoked = True
                message.Send()
            return ProviderAccepted()
        except Exception:
            return ProviderFailure(
                certainty=(
                    AcceptanceCertainty.UNKNOWN
                    if send_invoked
                    else AcceptanceCertainty.NOT_ACCEPTED
                ),
                error_code=(
                    DeliveryErrorCode.DELIVERY_AMBIGUOUS
                    if send_invoked
                    else DeliveryErrorCode.REQUEST_REJECTED
                ),
                diagnostic_code=(
                    "outlook_send_failed" if send_invoked else "outlook_compose_failed"
                ),
            )

    def _find_account(self, accounts: OutlookAccounts) -> OutlookAccount | None:
        for index in range(1, int(accounts.Count) + 1):
            account = accounts.Item(index)
            if str(account.SmtpAddress).casefold() == self._account_address:
                return account
        return None

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=False)
