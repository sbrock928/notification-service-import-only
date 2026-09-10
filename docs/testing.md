# Testing

Normal tests use an HTTP mock transport and an injected fake Outlook application. They require no
webhook, Outlook installation, Windows host, Microsoft credentials, or Graph tenant.

Run the automated gates with the development dependencies installed:

```bash
ruff check src tests
mypy src
pytest -q
```

Live checks are release gates, not unit tests. Run controlled sends to an approved mailbox and Teams
channel using the actual Windows account and Power Automate flow. Repeat the live suite when rotating
webhooks, changing the Outlook profile, or selecting either Graph provider.
