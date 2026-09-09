"""Provider-independent, immutable notification values."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from notification_service.errors import ValidationError


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
        """Read a local file before calling the client; the remote service never reads paths."""
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
    metadata: dict[str, str] = field(default_factory=dict, repr=False)

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
        if len(self.attachments) > 10:
            raise ValidationError("At most 10 attachments are supported")
        if sum(len(item.content) for item in self.attachments) > 20 * 1024**2:
            raise ValidationError("Attachments exceed the 20 MiB total limit")
        for item in self.attachments:
            if len(item.content) > 10 * 1024**2 or "/" in item.filename or "\\" in item.filename:
                raise ValidationError("Attachment is invalid or too large")
        if self.idempotency_key is not None and not re.fullmatch(
            r"[A-Za-z0-9_.:/-]{1,128}", self.idempotency_key
        ):
            raise ValidationError("Idempotency key has invalid characters")

    @property
    def all_recipients(self) -> tuple[Recipient, ...]:
        return self.to + self.cc + self.bcc

    @property
    def fingerprint(self) -> str:
        """Stable request identity used by an optional idempotency store."""
        import json

        value = {
            "to": [item.address for item in self.to],
            "cc": [item.address for item in self.cc],
            "bcc": [item.address for item in self.bcc],
            "subject": self.subject,
            "text": self.text,
            "html": self.html,
            "attachments": [
                {"filename": a.filename, "media_type": a.media_type, "sha256": a.sha256}
                for a in self.attachments
            ],
        }
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


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
