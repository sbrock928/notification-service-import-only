"""Microsoft Graph email adapter. No Graph SDK models leak into the public API."""

from __future__ import annotations

import asyncio
import base64
import ssl
from typing import Protocol
from urllib.parse import quote, urlparse

import httpx

from notification_service.models import (
    EmailNotification,
    ProviderAccepted,
    ProviderOutcome,
    ProviderRejected,
)


class AccessToken(Protocol):
    async def get(self) -> str: ...

    async def invalidate(self) -> None: ...

    async def aclose(self) -> None: ...


class ClientSecretToken:
    """Unattended Entra application credential for Microsoft Graph."""

    def __init__(self, tenant_id: str, client_id: str, client_secret: str) -> None:
        from azure.identity.aio import ClientSecretCredential

        self._credential = ClientSecretCredential(tenant_id, client_id, client_secret)

    async def get(self) -> str:
        token = await self._credential.get_token("https://graph.microsoft.com/.default")
        return token.token

    async def invalidate(self) -> None:
        await self._credential.close()

    async def aclose(self) -> None:
        await self._credential.close()


class GraphEmailProvider:
    def __init__(
        self,
        mailbox: str,
        token: AccessToken,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30,
    ) -> None:
        self.mailbox = mailbox
        self.token = token
        self.client = client or httpx.AsyncClient(
            verify=ssl.create_default_context(),
            timeout=httpx.Timeout(timeout_seconds, connect=5),
            follow_redirects=False,
            trust_env=True,
        )

    async def send(self, notification: EmailNotification) -> ProviderOutcome:
        token = await self.token.get()
        root = "https://graph.microsoft.com/v1.0/users/" + quote(self.mailbox, safe="")
        headers = {
            "Authorization": f"Bearer {token}",
            "Prefer": 'IdType="ImmutableId"',
            "client-request-id": notification.correlation_id,
        }
        message = {
            "subject": notification.subject,
            "body": {
                "contentType": "HTML" if notification.html else "Text",
                "content": notification.html or notification.text,
            },
            "toRecipients": [{"emailAddress": {"address": r.address}} for r in notification.to],
            "ccRecipients": [{"emailAddress": {"address": r.address}} for r in notification.cc],
            "bccRecipients": [{"emailAddress": {"address": r.address}} for r in notification.bcc],
        }
        reference: str | None = None
        try:
            draft = await self.client.post(root + "/messages", headers=headers, json=message)
            if draft.status_code not in {200, 201}:
                return self._rejected(draft, "draft_create", known=True)
            reference = draft.json().get("id")
            if not isinstance(reference, str):
                return ProviderRejected(
                    "invalid_provider_response", "Draft did not contain an ID", False
                )
            draft_url = root + "/messages/" + quote(reference, safe="")
            for attachment in notification.attachments:
                if len(attachment.content) < 3_000_000:
                    response = await self.client.post(
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
                        return self._rejected(response, "attachment", known=True)
                else:
                    session = await self.client.post(
                        draft_url + "/attachments/createUploadSession",
                        headers=headers,
                        json={
                            "AttachmentItem": {
                                "attachmentType": "file",
                                "name": attachment.filename,
                                "size": len(attachment.content),
                                "contentType": attachment.media_type,
                            },
                        },
                    )
                    if session.status_code not in {200, 201}:
                        return self._rejected(session, "upload_session", known=True)
                    upload_url = session.json().get("uploadUrl")
                    if not self._safe_upload_url(upload_url):
                        return ProviderRejected(
                            "unsafe_upload_url",
                            "Provider returned an invalid upload destination",
                            False,
                        )
                    chunk_size = 320 * 1024 * 10
                    for offset in range(0, len(attachment.content), chunk_size):
                        chunk = attachment.content[offset : offset + chunk_size]
                        end = offset + len(chunk) - 1
                        response = await self.client.put(
                            upload_url,
                            content=chunk,
                            headers={
                                "Content-Type": "application/octet-stream",
                                "Content-Length": str(len(chunk)),
                                "Content-Range": f"bytes {offset}-{end}/{len(attachment.content)}",
                            },
                        )
                        if response.status_code not in {200, 201, 202}:
                            return self._rejected(response, "attachment_upload", known=True)
            response = await self.client.post(draft_url + "/send", headers=headers)
            if response.status_code == 202:
                return ProviderAccepted(reference)
            return self._rejected(response, "send", known=False)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            return ProviderRejected("network_error", "Connection failed before acceptance", True)
        except httpx.HTTPError:
            return ProviderRejected("network_error", "Provider operation did not complete", False)
        except (KeyError, TypeError, ValueError):
            return ProviderRejected(
                "invalid_provider_response", "Provider response was malformed", False
            )

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

    async def _cleanup(self, reference: str) -> None:
        try:
            token = await self.token.get()
            root = "https://graph.microsoft.com/v1.0/users/" + quote(self.mailbox, safe="")
            async with asyncio.timeout(5):
                await self.client.delete(
                    root + "/messages/" + quote(reference, safe=""),
                    headers={"Authorization": f"Bearer {token}"},
                )
        except Exception:
            pass

    async def aclose(self) -> None:
        await self.client.aclose()
        await self.token.aclose()

    async def _noop(self) -> None:
        return None

    def _rejected(self, response: httpx.Response, phase: str, *, known: bool) -> ProviderRejected:
        status = response.status_code
        retryable = status in {408, 429, 500, 502, 503, 504}
        retry_after = response.headers.get("Retry-After")
        delay = float(retry_after) if retry_after and retry_after.isdigit() else None
        return ProviderRejected(
            f"graph_{phase}_{status}",
            "Microsoft Graph rejected the request",
            retryable,
            known,
            delay,
        )
