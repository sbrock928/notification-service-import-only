# Testing

Automated tests use HTTP mock transports and fake COM objects. They need no Outlook
installation, webhook, Azure tenant, or Microsoft credential.

Start with [development.md](development.md) for cloning, virtual-environment
creation, `pip-sync`, and editable installation.

```powershell
python -m pip install --upgrade pip pip-tools
.venv\Scripts\pip-sync.exe constraints/py313.txt
python -m pip install --no-deps -e ".[dev,graph]"
ruff check .
ruff format --check .
mypy src
pytest --cov=notification_service --cov-branch --cov-fail-under=90
python -m build
python -m pip check
```

The suites cover import/no-configuration behavior, immutable content, fingerprint
vectors, table escaping and omission counts, recipient/attachment limits, atomic
concurrency, wait/replay/conflict, leases/TTL/resolution, deterministic retry,
cancellation and late completion, lifecycle, log redaction boundaries, Outlook
serialization, Power Automate Teams webhook cards, and experimental Graph contracts.

Set up a separate opt-in test to send an Adaptive Card webhook to a controlled
workflow; never put a signed URL in source or test output. Real Outlook and Power Automate checks are
manual release gates, not unit tests.
