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

## Developer workflow

The repository is intentionally pip-based. Use a fresh Python 3.13 virtual
environment for local work; do not install project dependencies globally.

```bash
git clone <private-repository-url> notification-service-import-only
cd notification-service-import-only
git switch -c feature/short-description

python3.13 -m venv .venv
source .venv/bin/activate                 # Windows: .venv\\Scripts\\activate
python -m pip install --upgrade pip pip-tools
pip-sync constraints/py313.txt
python -m pip install --no-deps -e ".[dev,graph]"
```

`constraints/py313.txt` is the reviewed transitive lock set. `pip-sync` makes a
virtual environment reproducible by removing packages that are not in that set;
run it only inside the project virtual environment. The editable install places
this checkout on the import path. On Windows, install the Outlook extra instead
of (or in addition to) `graph`:

```powershell
python -m pip install --no-deps -e ".[dev,outlook-win32]"
```

If dependencies change, update the project requirement first, regenerate the
reviewed constraints in a disposable Python 3.13 environment, run the complete
gate, and review the diff before committing. Keep application secrets, signed
Power Automate URLs, and live credentials outside the repository.

Run the same checks used by CI from the repository root:

```bash
ruff check .
ruff format --check .
mypy src
pytest --cov=notification_service --cov-branch --cov-fail-under=90
python -m build
python -m pip check
```

The default test suite is offline. The Power Automate check is opt-in only:
provide `NOTIFICATION_TEST_PA_SIGNED_URL` and
`NOTIFICATION_TEST_PA_HOST_SUFFIX`, then run
`pytest -m 'integration and live'`. Real Outlook verification is a controlled
Windows release check, never a normal test run.

For changes, add or update a focused test, run the complete gate, and make small
sequential local commits using the intent described in
[REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md). Do not push from this workflow; a
reviewer decides when commits are published.

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

## Future implementation phases

The current package is Stage A. Future phases are deliberately incremental and
must preserve the provider-neutral content and delivery contracts.

For the short day-to-day command reference, see the dedicated
[developer guide](docs/development.md).

### Stage B — Graph email migration

1. Revalidate the Microsoft Graph API, permissions, upload-session behavior, and
   tenant policy against the release date.
2. Provision a least-privilege Entra application and restrict it to the fixed
   mailbox with Exchange application-access policy. Use `Mail.ReadWrite` and
   `Mail.Send` only as required by the draft/attachment/send flow.
3. Run the experimental provider contract suite with borrowed and explicitly
   owned token lifecycles, small and chunked attachments, escaped tables, and
   orphan-draft cleanup.
4. Run controlled direct-mailbox and shared operational tests, compare Sent Items,
   and verify unknown-result handling before changing composition from Outlook to
   Graph. No domain-model or caller change should be needed.

Graph code stays under `notification_service.experimental.graph` until these
checks are approved. A Graph email change is not a reason to add Graph imports to
the stable root package.

### Stage C — Teams transport decision

Recheck whether ordinary unattended Teams channel posting has a supported
application permission. If it still requires delegated `ChannelMessage.Send`,
Power Automate remains the active transport. `Teamwork.Migrate.All` is reserved
for migration scenarios and must not be used for routine notifications. If a new
transport is approved, implement it behind the existing typed Teams provider
port, preserve schema-v2 tables, and run the Teams contract suite before any
composition change.

### Stage D — hosted REST/microservice ingestion (future, separate runtime)

The REST service is not part of this import-only package. When remote callers are
needed, create a separately deployed API/application (or a separately owned
repository) with this boundary:

```text
REST API -> authenticated command/queue edge -> durable job worker
                                         -> NotificationClient (this package)
```

The implementation sequence is:

1. Define a versioned ingestion contract that accepts channel content, optional
   structured tables, source application, correlation ID, and idempotency key.
2. Authenticate and authorize the caller at the API edge; validate size, tenant,
   destination, and policy boundaries before enqueueing. Never accept provider
   secrets, arbitrary headers, or executable templates from callers.
3. Persist an atomic idempotency claim in the API/job store before enqueueing.
   The durable adapter must preserve this package's scoped conflict, wait/replay,
   lease, unknown, and operator-resolution semantics.
4. Return `202 Accepted` with an operation ID for accepted work. `queued` and
   `in_progress` are API/job states; `accepted`, `failed`, and `unknown` remain
   delivery states and must not be conflated.
5. Let the worker construct one typed client per channel, reuse the same
   idempotency key, and publish sanitized status. The API must not call Outlook,
   Graph, or Power Automate directly and must not implement business fan-out.
6. Add durable status lookup, authentication/audit logging, rate limits, retry
   policy, dead-letter/operator resolution, and deployment controls as separate
   capabilities. Keep notification content out of logs and keep persistent audit
   history separate from idempotency storage.
7. Roll out behind a versioned endpoint and contract tests. Existing in-process
   callers continue using this package until the hosted edge has passed load,
   security, and ambiguity/replay tests.

The detailed decision records and rollout gates live in
[MIGRATION_ROADMAP.md](docs/MIGRATION_ROADMAP.md) and
[docs/adrs](docs/adrs/README.md). No FastAPI, database, Redis, queue, Docker, or
Azure hosting runtime is introduced into this repository as part of Stage A.
