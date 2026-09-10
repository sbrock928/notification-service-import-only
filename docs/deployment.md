# Deployment and release checklist

Deploy the wheel into the existing long-running queue worker. Scheduling, queueing,
fan-out, and retry of business jobs remain outside this package.

## Required automated gates

- Azure DevOps Linux and Windows jobs pass on Python 3.13.
- The wheel installs from reviewed constraints and imports outside the source tree.
- Lint, format, strict mypy, 90% branch coverage, build, and pip check pass.
- Windows installs `.[dev,outlook-win32]` and runs offline fake-COM tests.

## Outlook release checks

- Run under the intended signed-in Windows user with classic Outlook configured.
- Confirm the exact `account_address` is present.
- Send a controlled direct-account email.
- Send a controlled shared-mailbox email with Exchange Send As permission.
- Verify the selected mailbox's Sent Items behavior.
- Verify text, escaped HTML tables, Unicode filenames, and supported attachments.
- Confirm one worker process owns the Outlook profile and shutdown drains work.

## Power Automate release checks

- Create or upgrade every destination to the non-premium **Send webhook alerts to a
  channel** workflow before deploying this package.
- Confirm each logical destination maps to the intended Flow and Teams channel.
- Run the opt-in Teams webhook integration test with simple and table messages.
- Review Flow/connector retries and the absence of end-to-end idempotency.
- Confirm proxy routing (including Zscaler proxy/CA settings when applicable),
  complete signed-URL secret rotation, and URL redaction.

Treat `UNKNOWN` as an operator-review state. Do not create a new key for an
immediate resend. Resolve it explicitly to accepted or failed after investigation.

Graph has no live release gate until migration Stage B. See
[MIGRATION_ROADMAP.md](MIGRATION_ROADMAP.md).
