# Deployment

Install the package in the existing worker. The initial email worker must run on Windows with Outlook
desktop installed, a configured profile, and the `outlook-win32` package extra. Teams delivery only
requires outbound HTTPS access to the configured Power Automate trigger endpoints.

Before production, verify:

- the worker's Outlook profile can send from the configured mailbox;
- Outlook security policy permits unattended object-model sends;
- HTML/text and supported attachment types work under the service account;
- every Teams destination resolves to the intended Power Automate flow and channel;
- trigger authentication, flow ownership, secret rotation, and connector retry policy;
- timeouts and lost final responses produce an operational review instead of blind resend;
- the upstream queue reuses idempotency keys on business-task retries;
- graceful shutdown calls `await client.aclose()`.

For Graph migration, separately verify tenant consent, email application-permission scope, the Teams
delegated-authentication flow, mailbox and channel scope, Conditional Access, token rotation, and
outbound Graph connectivity. Microsoft currently limits application-only channel posting to migration
scenarios, so an unattended client secret cannot replace the Power Automate Teams flow directly.
