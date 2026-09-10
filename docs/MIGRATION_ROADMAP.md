# Migration roadmap

## Stage A — current 0.1.0

Run as an imported library in the existing worker. Classic Outlook delivers email;
Power Automate schema v2 delivers Teams notifications. Keep scheduling, queues,
business record selection, fan-out, and persistent audit history in host systems.

## Stage B — Graph email

Revalidate Graph APIs and permissions, configure an Entra application, restrict it
to the fixed mailbox through tenant/Exchange policy, and verify `Mail.ReadWrite`
plus `Mail.Send`. Run provider contract and live draft/attachment/send/orphan tests.
Change only provider composition after operational approval.

## Stage C — Teams transport decision

Revalidate whether ordinary unattended channel sends have an appropriate
application permission. If they still require delegated `ChannelMessage.Send`,
retain Power Automate or select another approved transport. Never use
`Teamwork.Migrate.All` for routine notifications.

## Stage D — optional hosted REST ingestion (separate runtime)

If remote callers are later required, add a separately deployed REST/API runtime
or repository. It must be an authenticated queue-first edge that returns `202
Accepted` with an operation ID. It validates versioned content and tables, claims
durable scoped idempotency before enqueueing, and never calls providers directly.
The existing worker then uses this package's typed clients and delivery semantics.

An eventual authentication service should issue the access tokens used by that
edge. The edge validates issuer, audience, expiry, tenant, and scopes, maps the
caller to an allowed source application, and records security/audit events. The
worker uses a separate service identity; this package receives no user credentials
and does not implement login, sessions, or token issuance.

Keep `queued` and `in_progress` as API/job states; `accepted`, `failed`, and
`unknown` remain delivery states. A durable idempotency adapter must preserve
atomic claim, wait/replay, conflict, lease expiry, unknown resolution, and late
completion semantics. Add status lookup, authorization/audit logging, rate
limits, dead-letter handling, and deployment controls as separate capabilities.
Persistent history is an audit store, not an idempotency store. The hosted stage
does not add FastAPI, a database, Redis, a queue, Docker, or Azure runtime to this
import-only repository.

See the [developer workflow and phase guide](../README.md#developer-workflow) and
[ADR 009](adrs/009-hosted-rest-boundary.md).
