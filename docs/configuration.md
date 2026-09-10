# Configuration

The package never reads environment variables on import. The host application reads its secret store
and constructs providers explicitly.

## Initial providers

```python
import os

from notification_service import (
    PowerAutomateTeamsProvider,
    PowerAutomateWebhook,
    Win32OutlookEmailProvider,
)

teams_provider = PowerAutomateTeamsProvider({
    "ops-alerts": PowerAutomateWebhook(
        os.environ["PA_TEAMS_OPS_ALERTS_WEBHOOK"],
        authorization_token=os.environ.get("PA_TEAMS_USER_TOKEN"),
    ),
    "data-quality": os.environ["PA_TEAMS_DATA_QUALITY_WEBHOOK"],
})

email_provider = Win32OutlookEmailProvider(
    sender=os.environ.get("OUTLOOK_SHARED_MAILBOX"),
)
```

Never log webhook URLs, query strings, bearer tokens, message bodies, or attachment content. Keep the
destination mapping in trusted deployment configuration; application callers receive only logical
destination names.

The Windows worker account must have an initialized Outlook profile. A configured `sender` requires
the corresponding send-as or send-on-behalf-of permission.

## Future Graph providers

```python
from notification_service import (
    ClientSecretToken,
    GraphEmailProvider,
    GraphTeamsProvider,
    TeamsChannel,
)

token = ClientSecretToken(tenant_id, client_id, client_secret)
email_provider = GraphEmailProvider("shared-mailbox@contoso.com", token)
teams_provider = GraphTeamsProvider(
    {"ops-alerts": TeamsChannel(team_id, channel_id)},
    delegated_teams_token,
)
```

`delegated_teams_token` is an `AccessToken` implementation supplied by the host application's user
authentication component. Current Graph channel-message sends require delegated
`ChannelMessage.Send`; `ClientSecretToken` is not valid for routine Teams notifications. Email and
Teams also need separate token instances so each provider owns and closes its credential lifecycle.
