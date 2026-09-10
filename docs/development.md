# Developer guide

This repository builds a library, not a running service. Work on Python 3.13 and
keep the checkout free of credentials, signed webhook URLs, generated coverage
files, and live provider output.

## First checkout

```powershell
git clone <private-repository-url> notification-service-import-only
cd notification-service-import-only
git switch -c feature/short-description
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip pip-tools
.venv\Scripts\pip-sync.exe constraints/py313.txt
python -m pip install --no-deps -e ".[dev,graph]"
```

For Windows Outlook/fake-COM work, install `-e ".[dev,outlook-win32]"` instead
of (or in addition to) the `graph` extra. `pip-sync` is intentionally run only
inside this disposable virtual environment because it removes packages not
listed in the reviewed constraints.

Copy [env.example](../env.example) when documenting local settings. Keep the
resulting `.env` file untracked and replace every placeholder with a deployment
secret only on a controlled machine.

## Daily loop

Create a focused branch, make a small change, and add a focused offline test:

```powershell
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

Use the repository's pinned toolchain to regenerate it:

```powershell
pip-compile.exe pyproject.toml `
  --extra dev `
  --extra graph `
  --extra outlook-win32 `
  --output-file constraints/py313.txt `
  --resolver=backtracking
pip-sync.exe constraints/py313.txt
```

## External checks

The normal suite never contacts Microsoft services. Set
`NOTIFICATION_TEST_PA_SIGNED_URL` to one complete signed Power Automate URL only
for an approved controlled Flow, then run:

```powershell
pytest -m 'integration and live'
```

Real Outlook checks require a signed-in classic-Outlook profile on Windows and
belong to the release checklist, not the developer loop.

## Future phases

Read [README.md](../README.md#future-implementation-phases) for the Graph email
migration, Teams transport decision, and separately deployed REST ingestion plan.
For the active non-premium Teams workflow, follow
[power_automate_setup.md](power_automate_setup.md).
Read [REFACTOR_PLAN.md](REFACTOR_PLAN.md) before changing a public contract.
