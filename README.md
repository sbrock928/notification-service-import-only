# Import-only notification client

This Python library is called by an existing worker; importing it starts no server, queue,
scheduler, or background process.

The initial transports are intentionally explicit:

- Teams messages go to named Power Automate webhooks.
- Email goes through the locally configured Outlook desktop client using `win32com`.
- Microsoft Graph adapters implement the same ports for a later migration.

## Structure

```text
src/notification_service/
├── domain/                  # immutable models, outcomes, and stable errors
├── application/             # provider ports and delivery orchestration
├── providers/
│   ├── power_automate/      # initial Teams transport
│   ├── win32com/            # initial Outlook email transport
│   └── microsoft_graph/     # future email and Teams transports
├── client.py                # optional synchronous facade
└── __init__.py              # supported public imports
```

Provider-specific objects do not leak into the models or application service. Moving a channel
from Power Automate to Graph, or email from Outlook COM to Graph, only changes provider
construction. Graph Teams currently requires delegated user authentication; see
[provider behavior](docs/providers.md) before planning that migration.

## Install

Install the Windows Outlook extra on the machine that runs Outlook:

```bash
pip install "notification-service-import-only[outlook-win32]"
```

Install the Graph extra only when that migration is enabled:

```bash
pip install "notification-service-import-only[graph]"
```

## Teams through Power Automate

```python
import os

from notification_service import (
    NotificationClient,
    PowerAutomateTeamsProvider,
    PowerAutomateWebhook,
    TeamsNotification,
)

provider = PowerAutomateTeamsProvider({
    "ops-alerts": PowerAutomateWebhook(
        os.environ["PA_TEAMS_OPS_ALERTS_WEBHOOK"],
        authorization_token=os.environ.get("PA_TEAMS_USER_TOKEN"),
    ),
})
client = NotificationClient(provider)

result = await client.send(TeamsNotification(
    destination="ops-alerts",
    title="Scheduled job failed",
    text="Inspect the task logs.",
    idempotency_key=f"teams:job-failed:{job_id}",
    source_application="task-runner",
))

await client.aclose()
```

Callers select a logical destination, never a URL. The deployment-owned mapping determines the
Power Automate flow and Teams channel.

## Email through Outlook desktop

```python
from notification_service import (
    EmailNotification,
    NotificationClient,
    Recipient,
    Win32OutlookEmailProvider,
)

provider = Win32OutlookEmailProvider(sender="shared-mailbox@contoso.com")
client = NotificationClient(
    provider,
    allowed_email_domains=frozenset({"contoso.com"}),
)

result = await client.send(EmailNotification(
    to=(Recipient("ops@contoso.com"),),
    subject="Scheduled job failed",
    text="Inspect the task logs.",
    idempotency_key=f"email:job-failed:{job_id}",
    source_application="task-runner",
))

await client.aclose()
```

The Outlook adapter performs blocking COM work on a thread and serializes sends. Outlook must be
installed and configured under the Windows account running the worker.

Use the same idempotency key when the upstream queue retries. An `unknown` result means provider
acceptance could not be determined; do not automatically create a new key and resend.

See [architecture](docs/architecture.md), [provider behavior](docs/providers.md), and
[configuration](docs/configuration.md) for operational details.
