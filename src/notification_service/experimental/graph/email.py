"""Experimental global-cloud Microsoft Graph email adapter."""

from __future__ import annotations

import base64
from urllib.parse import quote, urlparse

import httpx

from notification_service.application.contracts import (
    AcceptanceCertainty,
    DeliveryErrorCode,
    DeliveryMetadata,
    ProviderAccepted,
    ProviderFailure,
    ProviderOutcome,
)
from notification_service.domain.models import EmailNotification
from notification_service.experimental.graph._base import GraphProviderBase
from notification_service.experimental.graph.auth import AccessToken
from notification_service.presentation.email import render_email
from notification_service.presentation.tables import TableRenderPolicy


class GraphEmailProvider(GraphProviderBase):
    def __init__(
        self,
        mailbox: str,
        token: AccessToken,
        *,
        client: httpx.AsyncClient | None = None,
        owns_token: bool = False,
        render_policy: TableRenderPolicy | None = None,
    ) -> None:
        if not mailbox:
            raise ValueError("A fixed Graph mailbox is required")
        super().__init__(token, client=client, owns_token=owns_token)
        self._mailbox = mailbox
        self._render_policy = render_policy or TableRenderPolicy()

    async def send(
        self,
        notification: EmailNotification,
        metadata: DeliveryMetadata,
    ) -> ProviderOutcome:
        root = "https://graph.microsoft.com/v1.0/users/" + quote(self._mailbox, safe="")
        headers = await self._headers(metadata.correlation_id)
        if isinstance(headers, ProviderFailure):
            return headers
        headers["Prefer"] = 'IdType="ImmutableId"'
        rendered = render_email(notification, self._render_policy)
        message = {
            "subject": notification.subject,
            "body": {
                "contentType": "HTML" if rendered.html is not None else "Text",
                "content": rendered.html or rendered.text,
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
        draft_url: str | None = None
        send_invoked = False
        try:
            draft = await self._client.post(root + "/messages", headers=headers, json=message)
            if draft.status_code not in {200, 201}:
                return self._response_failure(
                    draft,
                    "draft_create",
                    request_could_be_accepted=False,
                )
            try:
                reference = draft.json().get("id")
            except (AttributeError, ValueError):
                reference = None
            if not isinstance(reference, str) or not reference:
                return ProviderFailure(
                    certainty=AcceptanceCertainty.NOT_ACCEPTED,
                    error_code=DeliveryErrorCode.INVALID_PROVIDER_RESPONSE,
                    diagnostic_code="graph_draft_id_missing",
                )
            draft_url = root + "/messages/" + quote(reference, safe="")
            attachment_failure = await self._add_attachments(draft_url, headers, notification)
            if attachment_failure is not None:
                await self._delete_draft(draft_url, headers)
                return attachment_failure
            send_invoked = True
            response = await self._client.post(draft_url + "/send", headers=headers)
            if response.status_code == 202:
                return ProviderAccepted(provider_message_id=reference)
            failure = self._response_failure(
                response,
                "send",
                request_could_be_accepted=True,
            )
            if failure.certainty is AcceptanceCertainty.NOT_ACCEPTED:
                await self._delete_draft(draft_url, headers)
            return failure
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            if draft_url is not None:
                await self._delete_draft(draft_url, headers)
            return self._network_failure(request_could_be_accepted=send_invoked)
        except httpx.HTTPError:
            if draft_url is not None and not send_invoked:
                await self._delete_draft(draft_url, headers)
            return self._network_failure(request_could_be_accepted=send_invoked)

    async def _add_attachments(
        self,
        draft_url: str,
        headers: dict[str, str],
        notification: EmailNotification,
    ) -> ProviderFailure | None:
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
                    return self._response_failure(
                        response,
                        "attachment",
                        request_could_be_accepted=False,
                    )
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
                return self._response_failure(
                    session,
                    "upload_session",
                    request_could_be_accepted=False,
                )
            try:
                upload_url = session.json().get("uploadUrl")
            except (AttributeError, ValueError):
                upload_url = None
            if not self._safe_upload_url(upload_url):
                return ProviderFailure(
                    certainty=AcceptanceCertainty.NOT_ACCEPTED,
                    error_code=DeliveryErrorCode.INVALID_PROVIDER_RESPONSE,
                    diagnostic_code="graph_upload_url_invalid",
                )
            assert isinstance(upload_url, str)
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
                    return self._response_failure(
                        response,
                        "attachment_upload",
                        request_could_be_accepted=False,
                    )
        return None

    async def _delete_draft(self, draft_url: str, headers: dict[str, str]) -> None:
        try:
            await self._client.delete(draft_url, headers=headers)
        except httpx.HTTPError:
            return

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
            and not parsed.fragment
        )
