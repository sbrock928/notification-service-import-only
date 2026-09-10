# Configuration

The host reads environment variables or a secret store and passes values explicitly.
The library never discovers configuration during import.

## Outlook

```python
email_provider = Win32OutlookEmailProvider(
    account_address="worker@contoso.com",
    send_as_address="notifications@contoso.com",  # optional fixed shared mailbox
)
```

`account_address` must exist in the current classic-Outlook profile. A missing
account is a nonretryable pre-send failure. `send_as_address` is fixed for the
provider; the Windows identity must have Exchange Send As permission. Construct one
provider per profile and process.

## Power Automate

```python
teams_provider = PowerAutomateTeamsProvider(
    {"ops-alerts": PowerAutomateWebhook(signed_trigger_url)},
)
```

The endpoint is the complete URL copied from the non-premium **Send webhook alerts
to a channel** Teams workflow, including its provider-generated opaque/jumbled
query parameters. The provider POSTs a standard Adaptive Card webhook envelope;
the workflow posts that card to its configured channel. Redirects, userinfo,
fragments, bearer tokens, and arbitrary headers are rejected or unsupported. There
is no separate host-suffix setting: keep the complete URL in the deployment secret
store and never log it because its query string is a secret. Environment proxies
remain enabled for the provider-owned HTTP client.

## Client policy

```python
client = NotificationClient(
    provider,
    source_application="task-runner",
    policies=(AllowedEmailDomainsPolicy({"contoso.com"}),),
    retry_policy=RetryPolicy(max_attempts=2, total_timeout_seconds=120),
)
```

Domain allowlists are exact: `contoso.com` does not permit `sub.contoso.com`.
Production queue/redelivery callers provide an idempotency key. Lower table render
limits may be configured with `TableRenderPolicy`; hard input ceilings cannot be
raised.

## Experimental Graph

Graph imports are explicit:

```python
from notification_service.experimental.graph import ClientSecretToken, GraphEmailProvider
```

Tokens are borrowed by default. Set `owns_token=True` only when transferring
lifecycle ownership. Graph email uses a fixed mailbox and requires `Mail.ReadWrite`
plus `Mail.Send`, restricted with tenant/Exchange application-access policy. Graph
Teams remains delegated-auth research and must not use migration-only application
permission for ordinary messages.
