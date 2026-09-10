"""Future Outlook email adapter using Microsoft Graph."""

from __future__ import annotations

import base64
from urllib.parse import quote, urlparse

import httpx

from notification_service.domain.models import (
    EmailNotification,
    ProviderAccepted,
    ProviderOutcome,
    ProviderRejected,
)
from notification_service.providers.microsoft_graph._base import GraphProviderBase
from notification_service.providers.microsoft_graph.auth import AccessToken


class GraphEmailProvider(GraphProviderBase):
    def __init__(
        self,
        mailbox: str,
        token: AccessToken,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        super().__init__(token, client=client, timeout_seconds=timeout_seconds)
        self._mailbox = mailbox

    async def send(self, notification: EmailNotification) -> ProviderOutcome:
        root = "https://graph.microsoft.com/v1.0/users/" + quote(self._mailbox, safe="")
        headers = await self._headers(notification.correlation_id)
        headers["Prefer"] = 'IdType="ImmutableId"'
        message = {
            "subject": notification.subject,
            "body": {
                "contentType": "HTML" if notification.html else "Text",
                "content": notification.html or notification.text,
            },
            "toRecipients": [
                {"emailAddress": {"address": recipient.address}} for recipient in notification.to
            ],
            "ccRecipients": [
                {"emailAddress": {"address": recipient.address}} for recipient in notification.cc
            ],
            "bccRecipients": [
                {"emailAddress": {"address": recipient.address}} for recipient in notification.bcc
            ],
        }
        try:
            draft = await self._client.post(root + "/messages", headers=headers, json=message)
            if draft.status_code not in {200, 201}:
                return self._rejected(draft, "draft_create", known_not_accepted=True)
            reference = draft.json().get("id")
            if not isinstance(reference, str):
                return ProviderRejected(
                    "invalid_provider_response", "Draft did not contain an ID", False
                )
            draft_url = root + "/messages/" + quote(reference, safe="")
            attachment_result = await self._add_attachments(draft_url, headers, notification)
            if attachment_result is not None:
                return attachment_result
            response = await self._client.post(draft_url + "/send", headers=headers)
            if response.status_code == 202:
                return ProviderAccepted(reference)
            return self._rejected(response, "send", known_not_accepted=False)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return ProviderRejected("graph_network_error", "Connection failed", True)
        except httpx.HTTPError:
            return ProviderRejected(
                "graph_network_error", "Graph operation did not complete", False, False
            )
        except (KeyError, TypeError, ValueError):
            return ProviderRejected(
                "invalid_provider_response", "Provider response was malformed", False
            )

    async def _add_attachments(
        self,
        draft_url: str,
        headers: dict[str, str],
        notification: EmailNotification,
    ) -> ProviderRejected | None:
        for attachment in notification.attachments:
            if len(attachment.content) < 3_000_000:
                response = await self._client.post(
                    draft_url + "/attachments",
                    headers=headers,
                    json={
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": attachment.filename,
                        "contentType": attachment.media_type,
                        "contentBytes": base64.b64encode(attachment.content).decode("ascii"),
                    },
                )
                if response.status_code not in {200, 201}:
                    return self._rejected(response, "attachment", known_not_accepted=True)
                continue

            session = await self._client.post(
                draft_url + "/attachments/createUploadSession",
                headers=headers,
                json={
                    "AttachmentItem": {
                        "attachmentType": "file",
                        "name": attachment.filename,
                        "size": len(attachment.content),
                        "contentType": attachment.media_type,
                    }
                },
            )
            if session.status_code not in {200, 201}:
                return self._rejected(session, "upload_session", known_not_accepted=True)
            upload_url = session.json().get("uploadUrl")
            if not self._safe_upload_url(upload_url):
                return ProviderRejected(
                    "unsafe_upload_url", "Provider returned an invalid upload destination", False
                )
            chunk_size = 320 * 1024 * 10
            for offset in range(0, len(attachment.content), chunk_size):
                chunk = attachment.content[offset : offset + chunk_size]
                end = offset + len(chunk) - 1
                response = await self._client.put(
                    upload_url,
                    content=chunk,
                    headers={
                        "Content-Type": "application/octet-stream",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{len(attachment.content)}",
                    },
                )
                if response.status_code not in {200, 201, 202}:
                    return self._rejected(response, "attachment_upload", known_not_accepted=True)
        return None

    @staticmethod
    def _safe_upload_url(value: object) -> bool:
        if not isinstance(value, str):
            return False
        parsed = urlparse(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and (
                parsed.hostname == "outlook.office.com"
                or parsed.hostname.endswith(".outlook.office.com")
            )
            and not parsed.username
            and not parsed.password
        )
