from __future__ import annotations

from pathlib import Path

from notification_service import Attachment, EmailNotification, Recipient
from notification_service.models import ProviderAccepted, ProviderRejected
from notification_service.providers.win32com.outlook import Win32OutlookEmailProvider


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

    def __init__(self, *, fail_send: bool = False) -> None:
        self.Attachments = FakeAttachments()
        self.fail_send = fail_send
        self.sent = False

    def Send(self) -> None:
        self.sent = True
        if self.fail_send:
            raise RuntimeError("ambiguous COM failure")


class FakeOutlook:
    def __init__(self, message: FakeMessage) -> None:
        self.message = message

    def CreateItem(self, item_type: int) -> FakeMessage:
        assert item_type == 0
        return self.message


async def test_win32_provider_composes_and_sends_email() -> None:
    message = FakeMessage()
    provider = Win32OutlookEmailProvider(
        sender="shared@contoso.com",
        application_factory=lambda: FakeOutlook(message),
    )
    result = await provider.send(
        EmailNotification(
            to=(Recipient("ops@contoso.com"),),
            cc=(Recipient("owner@contoso.com"),),
            subject="Job failed",
            text="Inspect logs",
            attachments=(Attachment("report.txt", "text/plain", b"details"),),
        )
    )

    assert isinstance(result, ProviderAccepted)
    assert message.sent is True
    assert message.To == "ops@contoso.com"
    assert message.CC == "owner@contoso.com"
    assert message.SentOnBehalfOfName == "shared@contoso.com"
    assert message.Attachments.values == [("00-report.txt", b"details")]


async def test_win32_send_failure_is_ambiguous() -> None:
    message = FakeMessage(fail_send=True)
    provider = Win32OutlookEmailProvider(application_factory=lambda: FakeOutlook(message))
    result = await provider.send(
        EmailNotification((Recipient("ops@contoso.com"),), "Failure", "Body")
    )

    assert isinstance(result, ProviderRejected)
    assert result.known_not_accepted is False
    assert result.retryable is False
