# Import-only Notification Client

This package is designed to be imported by an existing task queue worker. Its initial live transport is a Power Automate HTTP webhook that invokes the Office 365 Outlook connector. Microsoft Graph remains an optional provider for a later deployment. The package owns no HTTP server, queue, scheduler, polling loop, database, or background worker.

## Install

```bash
uv add notification-service-import-only
```

## Async usage

```python
import os

from notification_service import EmailNotification, NotificationClient, PowerAutomateEmailProvider, Recipient

provider = PowerAutomateEmailProvider(
    os.environ["POWER_AUTOMATE_EMAIL_WEBHOOK"],
    authorization_token=os.environ.get("POWER_AUTOMATE_USER_TOKEN"),
)
client = NotificationClient(provider, allowed_domains=frozenset({"contoso.com"}))

result = await client.send(EmailNotification(
    to=(Recipient("ops@contoso.com"),),
    subject="Scheduled job failed",
    text="Inspect the task logs.",
    idempotency_key=f"job-failed:{job_id}",
    source_application="task-runner",
))

await client.aclose()
```

Use the same idempotency key when the upstream queue retries a task. `unknown` means the final provider response was not observed; do not generate a new key or automatically resend.

For synchronous scripts, use `SyncNotificationClient` around a factory that creates the async client. Do not use the sync facade inside an active event loop.

The complete incremental rebuild plan is in [docs/pr-guides/README.md](docs/pr-guides/README.md).

Teams delivery is a separate webhook provider. Each destination is explicitly
configured as a named Power Automate flow for one channel; callers cannot supply
arbitrary Teams URLs.
