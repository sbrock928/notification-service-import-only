# Configuration

The import-only package does not read environment variables on import. The host application constructs credentials and the provider explicitly.

```python
import os

from notification_service import PowerAutomateEmailProvider

provider = PowerAutomateEmailProvider(
    os.environ["POWER_AUTOMATE_EMAIL_WEBHOOK"],
    authorization_token=os.environ.get("POWER_AUTOMATE_USER_TOKEN"),
)
```

Use the host application's secret store or pipeline variables. Never commit a
secret, pass it in a container image, or log tokens. The sender mailbox is
configured inside the Power Automate flow. The recipient-domain policy is an
explicit constructor value.

For Teams, configure a mapping from a logical destination name to a Power
Automate channel webhook. Do not accept webhook URLs from notification callers.
