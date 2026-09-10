from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

from notification_service import (
    Attachment,
    EmailNotification,
    NotificationTable,
    Recipient,
    Win32OutlookEmailProvider,
)
from notification_service.application import (
    AcceptanceCertainty,
    DeliveryErrorCode,
    DeliveryMetadata,
    ProviderAccepted,
    ProviderFailure,
)


class FakeAccount:
    def __init__(self, address: str) -> None:
        self.SmtpAddress = address


class FakeAccounts:
    def __init__(self, *accounts: FakeAccount) -> None:
        self.values = accounts
        self.Count = len(accounts)

    def Item(self, index: int) -> FakeAccount:
        return self.values[index - 1]


class FakeSession:
    def __init__(self, accounts: FakeAccounts) -> None:
        self.Accounts = accounts


class FakeAttachments:
    def __init__(self) -> None:
        self.values: list[tuple[str, bytes]] = []

    def Add(self, path: str) -> object:
        self.values.append((Path(path).name, Path(path).read_bytes()))
        return object()


class FakeMessage:
    To = ""
    CC = ""
    BCC = ""
    Subject = ""
    Body = ""
    HTMLBody = ""
    SentOnBehalfOfName = ""
    SendUsingAccount: FakeAccount

    def __init__(self, *, fail_send: bool = False) -> None:
        self.Attachments = FakeAttachments()
        self.fail_send = fail_send
        self.sent = False

    def Send(self) -> None:
        self.sent = True
        if self.fail_send:
            raise RuntimeError("ambiguous COM failure")


class FakeOutlook:
    def __init__(self, message: FakeMessage, *accounts: FakeAccount) -> None:
        self.message = message
        self.Session = FakeSession(FakeAccounts(*accounts))
        self.created = 0

    def CreateItem(self, item_type: int) -> FakeMessage:
        assert item_type == 0
        self.created += 1
        return self.message


def metadata() -> DeliveryMetadata:
    return DeliveryMetadata(
        source_application="worker",
        correlation_id="corr",
        idempotency_key=None,
        channel="email",
    )


def notification() -> EmailNotification:
    return EmailNotification(
        to=(Recipient("ops@contoso.com"),),
        cc=(Recipient("owner@contoso.com"),),
        subject="Job failed",
        text="Inspect logs",
        attachments=(Attachment("report.txt", "text/plain", b"details"),),
        tables=(NotificationTable(columns=("ID",), rows=(("<1>",),)),),
    )


async def test_outlook_resolves_account_renders_and_sends_as_shared_mailbox() -> None:
    message = FakeMessage()
    account = FakeAccount("worker@contoso.com")
    outlook = FakeOutlook(message, FakeAccount("other@contoso.com"), account)
    provider = Win32OutlookEmailProvider(
        account_address="WORKER@contoso.com",
        send_as_address="notifications@contoso.com",
        application_factory=lambda: outlook,
    )
    result = await provider.send(notification(), metadata())
    await provider.aclose()

    assert isinstance(result, ProviderAccepted)
    assert message.SendUsingAccount is account
    assert message.SentOnBehalfOfName == "notifications@contoso.com"
    assert message.To == "ops@contoso.com"
    assert "&lt;1&gt;" in message.HTMLBody
    assert "<1>" in message.Body
    assert message.Attachments.values == [("00-report.txt", b"details")]


async def test_outlook_missing_account_fails_before_composition() -> None:
    outlook = FakeOutlook(FakeMessage(), FakeAccount("other@contoso.com"))
    provider = Win32OutlookEmailProvider(
        account_address="worker@contoso.com",
        application_factory=lambda: outlook,
    )
    result = await provider.send(notification(), metadata())
    await provider.aclose()
    assert isinstance(result, ProviderFailure)
    assert result.error_code is DeliveryErrorCode.SENDER_NOT_AVAILABLE
    assert outlook.created == 0


async def test_outlook_send_failure_is_ambiguous() -> None:
    outlook = FakeOutlook(FakeMessage(fail_send=True), FakeAccount("worker@contoso.com"))
    provider = Win32OutlookEmailProvider(
        account_address="worker@contoso.com",
        application_factory=lambda: outlook,
    )
    result = await provider.send(notification(), metadata())
    await provider.aclose()
    assert isinstance(result, ProviderFailure)
    assert result.certainty is AcceptanceCertainty.UNKNOWN
    assert result.error_code is DeliveryErrorCode.DELIVERY_AMBIGUOUS


async def test_outlook_worker_serializes_all_com_sends() -> None:
    active = 0
    maximum = 0
    lock = threading.Lock()
    release = threading.Event()

    class SlowMessage(FakeMessage):
        def Send(self) -> None:
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            release.wait(0.1)
            with lock:
                active -= 1

    provider = Win32OutlookEmailProvider(
        account_address="worker@contoso.com",
        application_factory=lambda: FakeOutlook(SlowMessage(), FakeAccount("worker@contoso.com")),
    )
    first = asyncio.create_task(provider.send(notification(), metadata()))
    second = asyncio.create_task(provider.send(notification(), metadata()))
    await asyncio.sleep(0.02)
    release.set()
    await asyncio.gather(first, second)
    await provider.aclose()
    assert maximum == 1


def test_outlook_configuration_guards() -> None:
    for arguments in (
        {"account_address": ""},
        {"account_address": "worker@contoso.com", "send_as_address": "bad\nvalue"},
    ):
        try:
            Win32OutlookEmailProvider(**arguments)  # type: ignore[arg-type]
        except ValueError:
            pass
        else:
            raise AssertionError("invalid Outlook configuration was accepted")


async def test_outlook_closed_and_unavailable_paths_are_known_failures() -> None:
    provider = Win32OutlookEmailProvider(
        account_address="worker@contoso.com",
        application_factory=lambda: (_ for _ in ()).throw(RuntimeError("start")),
    )
    result = await provider.send(notification(), metadata())
    assert isinstance(result, ProviderFailure)
    assert result.certainty is AcceptanceCertainty.NOT_ACCEPTED
    await provider.aclose()
    await provider.aclose()
    closed = await provider.send(notification(), metadata())
    assert isinstance(closed, ProviderFailure)

    if sys.platform != "win32":
        unavailable = Win32OutlookEmailProvider(account_address="worker@contoso.com")
        result = await unavailable.send(notification(), metadata())
        await unavailable.aclose()
        assert isinstance(result, ProviderFailure)
        assert result.error_code is DeliveryErrorCode.PROVIDER_UNAVAILABLE


async def test_outlook_account_lookup_and_compose_failures_are_not_ambiguous() -> None:
    class BrokenAccounts(FakeAccounts):
        def Item(self, index: int) -> FakeAccount:
            raise RuntimeError("lookup")

    broken_lookup = FakeOutlook(FakeMessage())
    broken_lookup.Session = FakeSession(BrokenAccounts(FakeAccount("worker@contoso.com")))
    provider = Win32OutlookEmailProvider(
        account_address="worker@contoso.com", application_factory=lambda: broken_lookup
    )
    result = await provider.send(notification(), metadata())
    await provider.aclose()
    assert isinstance(result, ProviderFailure)
    assert result.error_code is DeliveryErrorCode.SENDER_NOT_AVAILABLE

    class BrokenCompose(FakeOutlook):
        def CreateItem(self, item_type: int) -> FakeMessage:
            raise RuntimeError("compose")

    provider = Win32OutlookEmailProvider(
        account_address="worker@contoso.com",
        application_factory=lambda: BrokenCompose(FakeMessage(), FakeAccount("worker@contoso.com")),
    )
    result = await provider.send(notification(), metadata())
    await provider.aclose()
    assert isinstance(result, ProviderFailure)
    assert result.certainty is AcceptanceCertainty.NOT_ACCEPTED
    assert result.error_code is DeliveryErrorCode.REQUEST_REJECTED
