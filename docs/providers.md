# Power Automate and Outlook providers

`PowerAutomateEmailProvider` is the initial live provider. It posts a bounded
JSON payload to one configured HTTPS flow trigger. The flow owns the Outlook
connector, shared-mailbox connection, and actual send action. The provider
accepts `200`, `201`, `202`, or `204` as flow-trigger acceptance; this does not
claim Exchange delivery.

The temporary flow connection can use the operator's user authentication. Keep
the endpoint and token in the host application's secret store and never log
either value. When an Entra service identity is available, change the flow
connection or bearer-token acquisition in the host application; callers and
notification models stay unchanged.

Power Automate retry settings must be reviewed and disabled or made
idempotent. A connector retry after an ambiguous response can otherwise produce
duplicate email. The upstream task queue must reuse the same notification
idempotency key for its retry.

`GraphEmailProvider` remains available as an optional provider for a future
deployment. It is not required by the initial Power Automate installation.

## Teams channel webhooks

Teams messages use a separate provider in a later PR. Every destination is an
explicit configuration entry such as `ops-alerts -> https://...flow...`; a
caller cannot choose an arbitrary channel or webhook URL. This keeps channel
scope, flow ownership, and rotation operationally visible. Unsupported
destinations fail before the webhook is called.

`GraphEmailProvider` remains an optional alternative. It translates the same
provider-independent model into Microsoft Graph JSON, uses a draft for
attachments, and normalizes responses into `ProviderAccepted` or
`ProviderRejected`.

The service never claims delivery or read confirmation. A timeout after the send request may have reached Microsoft and is therefore returned as `unknown`; the upstream task must not automatically create a new notification key.
