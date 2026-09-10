# Provider behavior

## Power Automate Teams

`PowerAutomateTeamsProvider` maps a validated logical name such as `ops-alerts` to a deployment-owned
`PowerAutomateWebhook`. Unsupported destinations are rejected without an HTTP request. The payload
contains schema version, correlation and idempotency keys, source application, destination, title,
and text.

The flow should validate the payload, construct the supported Teams message or Adaptive Card, post
to its fixed channel, and return an optional `run_id` or `message_id`. A `2xx` response means flow
acceptance, not Teams delivery or user read confirmation.

Review or disable Power Automate retries unless the flow deduplicates on `idempotency_key`. A lost
response can otherwise produce duplicate messages.

## Win32 Outlook email

`Win32OutlookEmailProvider` creates an Outlook mail item using the current Windows user's Outlook
profile. It supports To/CC/BCC, text or HTML, an optional send-on-behalf-of mailbox, and bounded
attachments. Attachment bytes are copied to a private temporary directory because the Outlook COM
API accepts file paths; the directory is removed after Outlook has attached them.

COM is initialized inside the same worker thread that uses it. Sends are serialized. An error before
`MailItem.Send()` is known not to have sent; an error during `Send()` is ambiguous and is returned as
`unknown` by the application service.

## Microsoft Graph migration

`GraphEmailProvider` and `GraphTeamsProvider` consume the same `EmailNotification` and
`TeamsNotification` models. Teams destinations remain logical names, mapped to configured team and
channel IDs. Graph credentials are behind the `AccessToken` protocol; `ClientSecretToken` is the
included unattended credential implementation for email.

The two Graph providers do not currently use the same OAuth grant. Graph email can use application
permissions (`Mail.ReadWrite` for draft/attachment operations plus `Mail.Send`). Ordinary Teams
channel posting requires a delegated work-account token with `ChannelMessage.Send`; Graph application
permission is reserved for data migration and must not be used for routine notifications. The host
application must therefore supply a delegated `AccessToken` implementation to `GraphTeamsProvider`.

Graph adapters are migration targets, not required for the initial deployment. Confirm permissions,
mailbox/channel scoping, tenant policy, and production consent before selecting them.

## Shared delivery semantics

Providers return `ProviderAccepted` or `ProviderRejected`. `NotificationClient` maps these to:

- `accepted`: the provider accepted the operation;
- `failed`: the provider is known not to have accepted it;
- `unknown`: acceptance may have happened, so automatic retry could duplicate it.
