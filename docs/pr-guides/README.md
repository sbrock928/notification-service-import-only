# Incremental implementation guide

The repository can be reviewed as six independent changes. The order preserves the dependency rule:
domain depends on nothing, application depends on domain, and providers depend on both.

| PR | Commit | Result |
|---|---|---|
| 1 | `refactor(domain): define email and Teams contracts` | Immutable provider-neutral models and outcomes |
| 2 | `refactor(application): generalize notification orchestration` | Typed provider port, delivery states, retry, and idempotency |
| 3 | `feat(outlook): add win32com email provider` | Initial Outlook desktop email transport |
| 4 | `feat(teams): add Power Automate provider` | Initial named-destination Teams transport |
| 5 | `feat(graph): add future Microsoft Graph providers` | Drop-in migration adapters for Outlook and Teams |
| 6 | `test(docs): verify providers and document operations` | Tests, deployment gates, and examples |

After each PR, run `ruff check src tests`, `mypy src`, and `pytest -q`.
