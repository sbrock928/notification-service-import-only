"""Immutable values shared by every notification transport."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from notification_service.domain.errors import ValidationError

_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9_.:/-]{1,128}")
_DESTINATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


class Notification(Protocol):
    """The application-layer contract implemented by notification models."""

    idempotency_key: str | None
    correlation_id: str
    source_application: str

    @property
    def fingerprint(self) -> str: ...


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_common(idempotency_key: str | None, source_application: str) -> None:
    if idempotency_key is not None and not _IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        raise ValidationError("Idempotency key has invalid characters")
    if not source_application or len(source_application) > 128:
        raise ValidationError("Source application must be 1-128 characters")


@dataclass(frozen=True)
class Recipient:
    address: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+", self.address):
            raise ValidationError("Invalid email address")


@dataclass(frozen=True)
class Attachment:
    filename: str
    media_type: str
    content: bytes = field(repr=False)

    @classmethod
    def from_path(cls, path: str | Path, media_type: str) -> Attachment:
        """Read a local attachment explicitly before invoking a provider."""
        source = Path(path)
        return cls(source.name, media_type, source.read_bytes())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True)
class EmailNotification:
    to: tuple[Recipient, ...]
    subject: str
    text: str
    cc: tuple[Recipient, ...] = ()
    bcc: tuple[Recipient, ...] = ()
    html: str | None = None
    attachments: tuple[Attachment, ...] = ()
    idempotency_key: str | None = None
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    source_application: str = "unknown"

    def __post_init__(self) -> None:
        if not self.to:
            raise ValidationError("At least one recipient is required")
        if (
            not self.subject
            or len(self.subject) > 255
            or "\n" in self.subject
            or "\r" in self.subject
        ):
            raise ValidationError("Subject must be 1-255 characters without newlines")
        if not self.text and not self.html:
            raise ValidationError("An email body is required")
        if len(self.attachments) > 10:
            raise ValidationError("At most 10 attachments are supported")
        if sum(len(item.content) for item in self.attachments) > 20 * 1024**2:
            raise ValidationError("Attachments exceed the 20 MiB total limit")
        for item in self.attachments:
            if (
                not item.filename
                or not item.media_type
                or len(item.content) > 10 * 1024**2
                or "/" in item.filename
                or "\\" in item.filename
            ):
                raise ValidationError("Attachment is invalid or too large")
        _validate_common(self.idempotency_key, self.source_application)

    @property
    def all_recipients(self) -> tuple[Recipient, ...]:
        return self.to + self.cc + self.bcc

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "type": "email",
                "to": [item.address for item in self.to],
                "cc": [item.address for item in self.cc],
                "bcc": [item.address for item in self.bcc],
                "subject": self.subject,
                "text": self.text,
                "html": self.html,
                "attachments": [
                    {
                        "filename": item.filename,
                        "media_type": item.media_type,
                        "sha256": item.sha256,
                    }
                    for item in self.attachments
                ],
            }
        )


@dataclass(frozen=True)
class TeamsNotification:
    """A message addressed to a logical, preconfigured Teams destination."""

    destination: str
    text: str
    title: str | None = None
    idempotency_key: str | None = None
    correlation_id: str = field(default_factory=lambda: str(uuid4()))
    source_application: str = "unknown"

    def __post_init__(self) -> None:
        if not _DESTINATION.fullmatch(self.destination):
            raise ValidationError("Teams destination has an invalid name")
        if not self.text or len(self.text) > 28_000:
            raise ValidationError("Teams text must be 1-28000 characters")
        if self.title is not None and (not self.title or len(self.title) > 255):
            raise ValidationError("Teams title must be 1-255 characters")
        _validate_common(self.idempotency_key, self.source_application)

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "type": "teams",
                "destination": self.destination,
                "title": self.title,
                "text": self.text,
            }
        )


@dataclass(frozen=True)
class ProviderAccepted:
    provider_message_id: str | None
    accepted_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ProviderRejected:
    code: str
    message: str
    retryable: bool
    known_not_accepted: bool = True
    retry_after_seconds: float | None = None


ProviderOutcome = ProviderAccepted | ProviderRejected
