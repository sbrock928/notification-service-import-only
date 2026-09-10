"""Immutable provider-neutral notification content."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol

from notification_service.domain.errors import ValidationError

MIB = 1024 * 1024
MAX_BODY_BYTES = MIB
MAX_ATTACHMENTS = 10
MAX_ATTACHMENT_BYTES = 10 * MIB
MAX_TOTAL_ATTACHMENT_BYTES = 20 * MIB
MAX_TABLES = 3
MAX_TABLE_ROWS = 1_000
MAX_TABLE_COLUMNS = 50
MAX_CELL_CHARACTERS = 4_096
MAX_HEADING_CHARACTERS = 128
MAX_CAPTION_CHARACTERS = 255
MAX_TABLE_DATA_BYTES = 5 * MIB

_DESTINATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
_LOCAL_PART = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]{1,64}")
_DOMAIN = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
)
_MEDIA_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+")
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_INVALID_FILENAME = set('<>:"/\\|?*')


class Notification(Protocol):
    """Content accepted by the transport-neutral application service."""

    channel: ClassVar[str]

    @property
    def fingerprint(self) -> str: ...


def _utf8_size(value: str) -> int:
    return len(value.encode("utf-8"))


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        {"fingerprint_version": 2, "notification": value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class Recipient:
    """An address-only ASCII mailbox."""

    address: str

    def __post_init__(self) -> None:
        try:
            self.address.encode("ascii")
        except UnicodeEncodeError as error:
            raise ValidationError("Email addresses must contain ASCII characters only") from error
        if self.address.count("@") != 1:
            raise ValidationError("Invalid email address")
        local, domain = self.address.rsplit("@", 1)
        if not _LOCAL_PART.fullmatch(local) or not _DOMAIN.fullmatch(domain):
            raise ValidationError("Invalid email address")
        object.__setattr__(self, "address", f"{local}@{domain.lower()}")


def _safe_filename(value: str) -> str:
    filename = unicodedata.normalize("NFC", value)
    if (
        not filename
        or filename in {".", ".."}
        or len(filename) > 255
        or filename[-1] in {" ", "."}
        or any(character in _INVALID_FILENAME or ord(character) < 32 for character in filename)
        or filename.split(".", 1)[0].upper() in _WINDOWS_RESERVED
    ):
        raise ValidationError("Attachment filename is not safe")
    return filename


@dataclass(frozen=True, slots=True)
class Attachment:
    filename: str
    media_type: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "filename", _safe_filename(self.filename))
        if not _MEDIA_TYPE.fullmatch(self.media_type):
            raise ValidationError("Attachment media type is invalid")
        try:
            immutable_content = bytes(self.content)
        except (TypeError, ValueError) as error:
            raise ValidationError("Attachment content must be bytes-like") from error
        if len(immutable_content) > MAX_ATTACHMENT_BYTES:
            raise ValidationError("Attachment exceeds the 10 MiB limit")
        object.__setattr__(self, "content", immutable_content)

    @classmethod
    def from_path(cls, path: str | Path, media_type: str) -> Attachment:
        """Read at most one byte beyond the supported attachment size."""
        source = Path(path)
        with source.open("rb") as stream:
            content = stream.read(MAX_ATTACHMENT_BYTES + 1)
        return cls(source.name, media_type, content)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationTable:
    """A narrow table of caller-owned, display-ready strings."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...] = ()
    caption: str | None = None

    def __post_init__(self) -> None:
        columns = tuple(self.columns)
        rows = tuple(tuple(row) for row in self.rows)
        if not columns or len(columns) > MAX_TABLE_COLUMNS:
            raise ValidationError("A table must contain 1-50 columns")
        if len(rows) > MAX_TABLE_ROWS:
            raise ValidationError("A table cannot contain more than 1000 rows")
        for heading in columns:
            if not isinstance(heading, str) or not heading or len(heading) > MAX_HEADING_CHARACTERS:
                raise ValidationError(
                    "Table headings must be non-empty strings up to 128 characters"
                )
        for row in rows:
            if len(row) != len(columns):
                raise ValidationError("Every table row must match the column count")
            if any(not isinstance(cell, str) or len(cell) > MAX_CELL_CHARACTERS for cell in row):
                raise ValidationError("Table cells must be strings up to 4096 characters")
        if self.caption is not None and (
            not isinstance(self.caption, str)
            or not self.caption
            or len(self.caption) > MAX_CAPTION_CHARACTERS
        ):
            raise ValidationError("Table captions must be non-empty strings up to 255 characters")
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "rows", rows)

    @property
    def utf8_size(self) -> int:
        labels = (*(() if self.caption is None else (self.caption,)), *self.columns)
        return sum(_utf8_size(value) for value in labels) + sum(
            _utf8_size(cell) for row in self.rows for cell in row
        )

    def canonical_value(self) -> dict[str, object]:
        return {
            "caption": self.caption,
            "columns": list(self.columns),
            "rows": [list(row) for row in self.rows],
        }


def _normalize_tables(tables: tuple[NotificationTable, ...]) -> tuple[NotificationTable, ...]:
    normalized = tuple(tables)
    if len(normalized) > MAX_TABLES:
        raise ValidationError("A notification can contain at most three tables")
    if any(not isinstance(table, NotificationTable) for table in normalized):
        raise ValidationError("Notification tables must be NotificationTable values")
    if sum(table.utf8_size for table in normalized) > MAX_TABLE_DATA_BYTES:
        raise ValidationError("Notification table data exceeds the 5 MiB limit")
    return normalized


@dataclass(frozen=True, slots=True, kw_only=True)
class EmailNotification:
    channel: ClassVar[str] = "email"
    to: tuple[Recipient, ...]
    subject: str
    text: str
    cc: tuple[Recipient, ...] = ()
    bcc: tuple[Recipient, ...] = ()
    html: str | None = None
    attachments: tuple[Attachment, ...] = ()
    tables: tuple[NotificationTable, ...] = ()

    def __post_init__(self) -> None:
        to, cc, bcc = tuple(self.to), tuple(self.cc), tuple(self.bcc)
        attachments = tuple(self.attachments)
        if not to:
            raise ValidationError("At least one recipient is required")
        if any(not isinstance(item, Recipient) for item in (*to, *cc, *bcc)):
            raise ValidationError("Email recipients must be Recipient values")
        addresses = [recipient.address.casefold() for recipient in (*to, *cc, *bcc)]
        if len(addresses) != len(set(addresses)):
            raise ValidationError("Duplicate recipients across To, CC, and BCC are not allowed")
        if (
            not self.subject
            or len(self.subject) > 255
            or "\r" in self.subject
            or "\n" in self.subject
        ):
            raise ValidationError("Subject must be 1-255 characters without newlines")
        if not self.text or _utf8_size(self.text) > MAX_BODY_BYTES:
            raise ValidationError("Email text must be non-empty and no larger than 1 MiB")
        if self.html is not None and _utf8_size(self.html) > MAX_BODY_BYTES:
            raise ValidationError("Email HTML cannot exceed 1 MiB")
        if len(attachments) > MAX_ATTACHMENTS:
            raise ValidationError("At most 10 attachments are supported")
        if any(not isinstance(item, Attachment) for item in attachments):
            raise ValidationError("Email attachments must be Attachment values")
        if sum(len(item.content) for item in attachments) > MAX_TOTAL_ATTACHMENT_BYTES:
            raise ValidationError("Attachments exceed the 20 MiB total limit")
        object.__setattr__(self, "to", to)
        object.__setattr__(self, "cc", cc)
        object.__setattr__(self, "bcc", bcc)
        object.__setattr__(self, "attachments", attachments)
        object.__setattr__(self, "tables", _normalize_tables(self.tables))

    @property
    def all_recipients(self) -> tuple[Recipient, ...]:
        return self.to + self.cc + self.bcc

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "type": self.channel,
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
                "tables": [table.canonical_value() for table in self.tables],
            }
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TeamsNotification:
    """A message addressed to a logical, preconfigured Teams destination."""

    channel: ClassVar[str] = "teams"
    destination: str
    text: str
    title: str | None = None
    tables: tuple[NotificationTable, ...] = ()

    def __post_init__(self) -> None:
        if not _DESTINATION.fullmatch(self.destination):
            raise ValidationError("Teams destination has an invalid name")
        if not self.text or len(self.text) > 28_000:
            raise ValidationError("Teams text must be 1-28000 characters")
        if self.title is not None and (not self.title or len(self.title) > 255):
            raise ValidationError("Teams title must be 1-255 characters")
        object.__setattr__(self, "tables", _normalize_tables(self.tables))

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            {
                "type": self.channel,
                "destination": self.destination,
                "title": self.title,
                "text": self.text,
                "tables": [table.canonical_value() for table in self.tables],
            }
        )
