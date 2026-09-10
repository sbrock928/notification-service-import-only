# Production-Grade Notification Service Refactor

Status: approved for implementation on 2026-09-09.

## Scope and boundaries

This package remains an import-only Python 3.13 library. Calling applications and
queue workers decide what to send and send immediately; scheduling, persistence,
fan-out, business templates, and hosted APIs remain outside the package.

The stable transports are classic Outlook through Win32 COM for email and Power
Automate for Teams. Microsoft Graph remains experimental migration code. Calling
applications provide display-ready strings, headings, ordering, and records. The
library validates, escapes, bounds, summarizes, and renders that content without
interpreting an application schema or querying application data.

## Stable contracts

The root package exports `Recipient`, `Attachment`, `NotificationTable`,
`EmailNotification`, `TeamsNotification`, `TableRenderPolicy`,
`NotificationClient`, `SyncNotificationClient`, `DeliveryState`,
`DeliveryErrorCode`, `DeliveryResult`, `RetryPolicy`,
`AllowedEmailDomainsPolicy`, `InMemoryIdempotencyStore`,
`Win32OutlookEmailProvider`, `PowerAutomateWebhook`, and
`PowerAutomateTeamsProvider`, together with stable exceptions. Provider ports,
delivery metadata, provider outcomes, rendering internals, and idempotency
protocols are advanced application contracts. Graph lives under
`notification_service.experimental.graph`.

Notification models are frozen, slotted, keyword-only content values. A client is
configured with a required `source_application` and one typed channel provider.
`idempotency_key` and `correlation_id` are delivery arguments to `send()`. A
missing correlation ID is generated, and results always return the delivery
correlation ID. Idempotency replay returns the original delivery correlation ID.

## Structured tables

`NotificationTable` contains an optional caption, ordered column headings, and
ordered rows of display-ready strings. Tables are optional; a notification may
contain zero through three. There is no HTML input, callback, record mapping,
nested component, or general template engine.

Hard limits are 1,000 rows per table, 50 columns, 4,096 characters per cell, 128
characters per heading, 255 characters per caption, and 5 MiB of UTF-8 table data
per notification. Full, untruncated content participates in a versioned canonical
JSON fingerprint. Default presentation limits are 100 rows and 12 columns per
table. Leading values are rendered and exact omitted-row and omitted-column counts
are stated; rendering may reduce rows further to meet channel limits.

Email uses shared escaped, semantic, conservatively styled HTML and accessible
plain text. Table cells are always text. Caller HTML is trusted transport input,
but non-empty plain text is required and each final representation is limited to
1 MiB. Power Automate emits bounded Adaptive Card webhook payloads with structured
tables and omission summaries; the
Flow owns final Teams or Adaptive Card presentation. All Flows must accept v2
before deployment. Simple v2 messages carry an empty `tables` array.

## Domain rules

- ASCII mailbox addresses without display names; case-insensitive duplicates
  across To, CC, and BCC are invalid.
- Exact lowercase email-domain policy matching.
- Ten attachments maximum, 10 MiB each and 20 MiB total. Contents normalize to
  bytes; bounded path reads and safe normalized Unicode filenames are required.
- Teams text is non-empty and at most 28,000 characters. Titles are optional and
  at most 255 characters.
- Delivery metadata and destinations use bounded header-safe forms.
- Fingerprints include content, recipients, attachments, and full tables, but not
  source, key, or correlation ID.

## Delivery, retry, and lifecycle

Results have `ACCEPTED`, `FAILED`, or `UNKNOWN` state, correlation ID, optional
provider message ID, attempts, and an optional stable error code. Internal
provider failures state whether non-acceptance is proven or acceptance is unknown,
whether retry is safe, an optional bounded Retry-After, and a sanitized diagnostic.

Retries are limited to proven non-acceptance. `RetryPolicy` defaults to two
attempts (configurable one through three), a total 120-second budget, full jitter
with a 0.5-second base and 5-second cap, and Retry-After capped at 30 seconds and
the remaining budget. HTTP connect/pool timeouts are 5 seconds and read/write
timeouts are 30 seconds. Lost responses, read/write failures, 408, 5xx, and Power
Automate 429 are unknown unless a provider-specific contract proves pre-acceptance.

The client is single-event-loop owned, supports concurrent tasks on that loop,
owns and closes its provider, rejects work after close, tracks invoked attempts,
and drains them for 30 seconds. Cancellation before invocation releases an
idempotency claim. Cancellation during a retry delay stores the last proven
failure. Cancellation or timeout after invocation stores unknown; a definitive
late completion refines the stored result. The sync facade owns a private loop
thread, creates its client there with a synchronous factory, and shuts down safely
even when construction fails.

## Idempotency

Keys are scoped by source application, channel, and caller key. An atomic
claim/wait/complete/resolve protocol replaces check-then-put. Identical concurrent
requests wait and replay one result; different fingerprints conflict immediately.
A wait exhausting the send budget returns `UNKNOWN/in_progress_timeout` without
sending. Accepted and known-failed results expire after a configurable 24-hour
TTL. Unknown results never expire automatically and require an operator resolution
to a final accepted or failed result. Expired leases become unknown rather than
retryable. The default lease is 150 seconds.

## Security and observability

The library logs through `notification_service` without configuring handlers.
Structured records include correlation, source, channel, logical destination,
provider, attempt, duration, state, stable error code, sanitized diagnostic, and
idempotency status. Recipient addresses, titles, bodies, tables, attachment names
or bytes, signed URLs and query strings, tokens, secrets, and authorization
headers are never logged.

Power Automate accepts one complete provider-generated signed HTTPS URL per
logical destination. The opaque signature and other jumbled query values stay
embedded in that single secret; there is no separate host-suffix configuration.
Userinfo and fragments are rejected, redirects are disabled, environment proxies
remain enabled, and arbitrary headers and bearer tokens are unsupported.
Any 2xx response means trigger acceptance.

Outlook uses one dedicated serial COM worker per provider. It resolves a required
profile `account_address`, optionally sets a fixed shared-mailbox
`send_as_address`, fails before send if the account is missing, and accepts only
after `Send()` returns. Deployment uses classic Outlook in a long-running signed-in
user session with one process per profile.

## Implementation sequence

1. Record this plan; add architecture/characterization tests, Python 3.13 package
   gates, reviewed constraints, and an Azure DevOps validation pipeline.
2. Build immutable domain values, structured presentation, versioned
   fingerprints, validation, and the deliberate public API.
3. Introduce atomic idempotency claims, wait/replay, TTL, leases, conflicts, and
   explicit resolution.
4. Add explicit acceptance certainty, stable errors, total-budget retry, injected
   time/random/sleep, and deterministic tests.
5. Add cancellation tracking, late refinement, async lifecycle, bounded close,
   loop ownership, and sanitized structured logging.
6. Replace the Outlook adapter with a serial COM worker and explicit account and
   Send-As selection using the shared email renderer.
7. Restrict Power Automate configuration and implement non-premium Teams webhook
card payloads,
   classification, golden tests, and an opt-in integration test.
8. Rebuild the sync facade around a synchronous factory created on its private
   event-loop thread with exception-safe lifecycle.
9. Move and normalize Graph under the experimental namespace with explicit token
   ownership, phase-aware email behavior, orphan cleanup, and conservative Teams
   presentation.
10. Complete provider contract suites, ADRs, configuration, testing, deployment,
    and migration documentation.

Implementation is delivered as sequential local commits without pushing.

## Quality gates

```powershell
python -m pip install --upgrade pip
python -m pip install pip-tools
.venv\Scripts\pip-sync.exe constraints/py313.txt
python -m pip install --no-deps -e ".[dev,graph]"
ruff check .
ruff format --check .
mypy src
pytest --cov=notification_service --cov-branch --cov-fail-under=90
python -m build
python -m pip check
```

Windows additionally installs `.[dev,outlook-win32]` on Python 3.13 and runs
offline fake-COM tests. Release verification includes controlled direct-account
and shared-mailbox sends, Sent Items verification, and an opt-in Teams webhook
integration test. Graph has no live release gate.
