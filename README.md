# Notification service client

An import-only Python 3.13 library for immediate email and Teams notifications.
Importing it starts no server, queue, scheduler, network call, worker thread, or
environment lookup.

- Classic Outlook/Win32 COM is the active email transport.
- Power Automate HTTP-trigger Flows are the active Teams transport.
- Microsoft Graph is experimental migration code.
- Calling applications select records and provide display-ready strings.
- This package validates, escapes, bounds, summarizes, and presents optional tables.

## Install

Install from the private artifact feed with pip. The Windows worker needs the
Outlook extra:

```bash
python -m pip install "notification-service-import-only[outlook-win32]==0.1.0"
```

Graph migration experiments additionally use the `graph` extra. Python 3.12 and
non-pip workflows are unsupported.

## Email example

```python
from notification_service import (
    AllowedEmailDomainsPolicy,
    EmailNotification,
    NotificationClient,
    NotificationTable,
    Recipient,
    Win32OutlookEmailProvider,
)

table = NotificationTable(
    caption="Exception records",
    columns=("Record ID", "Created", "Reason"),
    rows=(("1234", "2026-09-09 09:15 UTC", "Invalid status"),),
)

async with NotificationClient(
    Win32OutlookEmailProvider(
        account_address="worker@contoso.com",
        send_as_address="notifications@contoso.com",
    ),
    source_application="task-runner",
    policies=(AllowedEmailDomainsPolicy({"contoso.com"}),),
) as client:
    result = await client.send(
        EmailNotification(
            to=(Recipient("ops@contoso.com"),),
            subject="Import exceptions",
            text="The import produced exception records.",
            tables=(table,),
        ),
        idempotency_key=f"email:import:{job_id}",
        correlation_id=upstream_correlation_id,
    )
```

Tables are optional. A simple email uses the same model with no `tables` argument.
HTML is trusted caller content, but a non-empty plain-text body is always required.
Table values are always escaped and never interpreted as HTML.

## Teams example

```python
import os

from notification_service import (
    NotificationClient,
    PowerAutomateTeamsProvider,
    PowerAutomateWebhook,
    TeamsNotification,
)

provider = PowerAutomateTeamsProvider(
    {"ops-alerts": PowerAutomateWebhook(os.environ["PA_TEAMS_OPS_ALERTS_SIGNED_URL"])},
    allowed_host_suffixes={"logic.azure.com"},
)

async with NotificationClient(
    provider,
    source_application="task-runner",
) as client:
    result = await client.send(
        TeamsNotification(
            destination="ops-alerts",
            title="Scheduled job failed",
            text="Inspect the task logs.",
        ),
        idempotency_key=f"teams:job-failed:{job_id}",
    )
```

The package sends schema v2 only. Every configured Flow must support it before this
version is deployed. A `2xx` response means that the Flow accepted the trigger,
not that Teams delivered or a user read the message.

Use the same key for upstream redelivery. `UNKNOWN` means acceptance cannot be
proved; never generate a new key and resend automatically. See the
[architecture](docs/architecture.md), [provider contracts](docs/providers.md),
and [deployment checklist](docs/deployment.md).
