"""Small application policies applied before provider invocation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from notification_service.domain.errors import ValidationError
from notification_service.domain.models import EmailNotification, Notification

_DOMAIN = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
)


class NotificationPolicy(Protocol):
    def validate(self, notification: Notification) -> None: ...


@dataclass(frozen=True, slots=True)
class AllowedEmailDomainsPolicy:
    domains: frozenset[str]

    def __init__(self, domains: Iterable[str]) -> None:
        normalized = frozenset(domain.lower().rstrip(".") for domain in domains)
        if not normalized or any(not _DOMAIN.fullmatch(domain) for domain in normalized):
            raise ValueError("Allowed email domains must be exact canonical domains")
        object.__setattr__(self, "domains", normalized)

    def validate(self, notification: Notification) -> None:
        if not isinstance(notification, EmailNotification):
            return
        if any(
            recipient.address.rsplit("@", 1)[1].lower() not in self.domains
            for recipient in notification.all_recipients
        ):
            raise ValidationError("External recipients are prohibited by client policy")
