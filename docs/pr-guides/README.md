# Import-only rebuild PR guide

This guide intentionally uses small, reviewable commits. Each PR is self-contained at its boundary and has one clear reason to exist. The complete implementation for every step is already present in the matching source files, so you can rebuild the package by applying the PRs in order or by cherry-picking the commits from this repository.

The final shape is deliberately small:

```text
upstream task worker
        │
        ▼
NotificationClient.send(notification)
        │
        ▼
EmailProvider (fake or Power Automate webhook)
        │
        ▼
Power Automate → Office 365 Outlook
```

There is no FastAPI app, CLI, Docker image, Celery integration, Redis dependency, database, polling process, or notification-owned scheduler.

## PR order

| PR | Commit message | Result |
|---|---|---|
| 1 | `chore: scaffold import-only notification package` | Installable package, immutable models, provider port, stable errors |
| 2 | `feat(service): add direct notification client and idempotency` | Async direct send, conservative retry, process-local duplicate protection |
| 3 | `feat(power-automate): add Outlook webhook provider` | Power Automate HTTP trigger, shared-mailbox flow contract, and attachments |
| 4 | `test: add fake provider and import-only behavior tests` | Deterministic tests for accepted, failed, unknown, and duplicate sends |
| 5 | `feat(teams): add explicitly configured channel webhook provider` | Named Teams channel destinations through Power Automate |
| 6 | `docs: document import-only integration and release gates` | Usage, configuration, live Microsoft checks, and upstream-worker guide |
| 7 | `fix(service): enforce configured internal recipient domains` | Optional internal-domain policy and its test |
| 8 | `fix(client): type synchronous facade safely` | Final sync-facade typing cleanup |

## Rebuild procedure

Create an empty repository, then apply each guide in order. After every PR run:

```bash
uv sync --extra dev
uv run ruff check src tests
uv run mypy src
uv run pytest
```

Do not add a web framework or queue to the package. The calling application owns task scheduling and decides whether to call the async client directly or use the sync facade. The initial Power Automate connection may be the operator's user authentication; migrate it to an Entra service identity later.
