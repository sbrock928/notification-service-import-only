# Developer guide

This repository builds a library, not a running service. Work on Python 3.13 and
keep the checkout free of credentials, signed webhook URLs, generated coverage
files, and live provider output.

## First checkout

```bash
git clone <private-repository-url> notification-service-import-only
cd notification-service-import-only
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip pip-tools
pip-sync constraints/py313.txt
python -m pip install --no-deps -e ".[dev,graph]"
```

On Windows PowerShell, use `py -3.13 -m venv .venv`,
`.venv\\Scripts\\Activate.ps1`, and install
`-e ".[dev,outlook-win32]"` for fake-COM tests. `pip-sync` is intentionally run
only inside this disposable virtual environment because it removes packages not
listed in the reviewed constraints.

## Daily loop

Create a focused branch, make a small change, and add a focused offline test:

```bash
git switch -c feature/short-description
pytest -q tests/test_domain.py
ruff check .
ruff format --check .
mypy src
pytest --cov=notification_service --cov-branch --cov-fail-under=90
```

Before review, run the complete commands in [testing.md](testing.md), including
`python -m build` and `python -m pip check`. Keep commits sequential and
descriptive; do not push from a local implementation session.

## Dependency updates

Change `pyproject.toml`, regenerate `constraints/py313.txt` in a disposable
Python 3.13 environment, and inspect every lockfile change. Re-run the complete
gate on Linux and Windows. Do not use an unreviewed floating dependency in CI.

## External checks

The normal suite never contacts Microsoft services. Set both
`NOTIFICATION_TEST_PA_SIGNED_URL` and `NOTIFICATION_TEST_PA_HOST_SUFFIX` only for
an approved controlled Flow, then run:

```bash
pytest -m 'integration and live'
```

Real Outlook checks require a signed-in classic-Outlook profile on Windows and
belong to the release checklist, not the developer loop.

## Future phases

Read [README.md](../README.md#future-implementation-phases) for the Graph email
migration, Teams transport decision, and separately deployed REST ingestion plan.
Read [REFACTOR_PLAN.md](REFACTOR_PLAN.md) before changing a public contract.
