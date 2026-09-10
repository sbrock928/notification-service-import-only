# Power Automate Teams webhook setup

This package targets the Microsoft Teams **Send webhook alerts to a channel**
workflow template. It does not require a Power Automate Premium license. Do not
choose the generic **When an HTTP request is received** trigger; that is a
different trigger and is not the deployment described here.

Microsoft documents this workflow as an incoming webhook backed by the Teams
connector. The generated URL is a secret: anyone who has it can post to the
configured channel.

## Create one workflow for each channel

1. Open Microsoft Teams and open the target team and channel.
2. Select the channel's **More options (...)** menu and choose **Workflows**.
3. Search for **Send webhook alerts to a channel** and select that template.
4. Select the target Team and Channel in the setup dialog. Use the intended
   Microsoft 365 account for the workflow connection.
5. Select **Save** (or **Add workflow**) and wait for the workflow to be created.
6. Open the workflow details and choose **Copy webhook link**. Save the complete
   URL in the worker's secret store. Do not split it into a host, token, or
   custom header, and do not paste it into source control.
7. Add a co-owner who can maintain the workflow if the original owner leaves.
   Confirm the workflow is turned on and that the Teams connection is healthy.
8. If the application sends to another channel, repeat these steps and construct
   a separate provider/client for that channel. Each channel has its own URL.

The template's trigger is the Teams webhook trigger and its default actions
process the standard `type: message` Adaptive Card envelope emitted by this
package. The notification library renders titles, text, tables, and explicit
omission summaries into that card. The workflow owns the final channel post.

## Configure the Windows worker

Copy [env.example](../env.example) to an untracked `.env` only if your host
explicitly loads dotenv files. Otherwise configure these values in the worker's
secret store:

```powershell
$env:PA_TEAMS_OPS_ALERTS_SIGNED_URL = "<complete copied workflow URL>"
```

Construct one provider/client per channel and pass its complete URL as one string:

```python
provider = PowerAutomateTeamsProvider(
    PowerAutomateWebhook(os.environ["PA_TEAMS_OPS_ALERTS_SIGNED_URL"]),
)
```

The provider uses the normal Windows proxy settings, does not add bearer or
custom authorization headers, and disables redirects. Keep URL query strings out
of logs and diagnostic output.

## Zscaler and corporate proxies

`httpx` honors `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, and `NO_PROXY` when the
provider owns its client (`trust_env=True`). It does not evaluate a Windows PAC
file or automatically import every proxy setting from Internet Options. If
Zscaler requires an explicit proxy, set the approved proxy address in the worker
process or pass it when constructing the provider:

```powershell
$env:HTTPS_PROXY = "http://proxy.contoso.com:8080"
$env:HTTP_PROXY = $env:HTTPS_PROXY
# Set NO_PROXY only for hosts that corporate policy explicitly allows direct.
$env:NO_PROXY = ""
```

```python
provider = PowerAutomateTeamsProvider(
    PowerAutomateWebhook(os.environ["PA_TEAMS_OPS_ALERTS_SIGNED_URL"]),
    proxy=os.environ.get("HTTPS_PROXY"),
)
```

Do not put proxy usernames, passwords, or signed webhook URLs in source control
or logs. If Zscaler performs TLS inspection, Python must trust the Zscaler root
CA. Prefer the reviewed corporate CA bundle through `SSL_CERT_FILE` rather than
disabling certificate verification:

```powershell
$env:SSL_CERT_FILE = "C:\ProgramData\Contoso\certs\zscaler-root-bundle.pem"
```

Do not set `verify=False` in production. Ask the network team for the approved
proxy hostname/port and CA-bundle path; a PAC URL alone is not sufficient for
this client.

For a safe connectivity check that does not print the signed query string:

```powershell
$uri = [Uri]$env:NOTIFICATION_TEST_PA_SIGNED_URL
Test-NetConnection -ComputerName $uri.DnsSafeHost -Port 443
```

Then run the smoke test. A connect or pool timeout usually indicates routing or
proxy configuration. A read/write timeout is ambiguous: the webhook may already
have been accepted, so investigate the workflow run history before retrying with
a new idempotency key.

## Run the smoke test

Use a controlled channel and a newly generated idempotency key:

```powershell
$env:NOTIFICATION_TEST_PA_SIGNED_URL = "<complete copied workflow URL>"
py -3.13 teams_channel_smoke_test.py --destination ops-alerts
```

A successful HTTP 2xx proves that the workflow accepted the webhook. Confirm the
message is visible in the selected Teams channel and inspect the workflow run
history if it is not. The smoke test is intentionally opt-in and is not part of
the offline unit-test suite.

## Payload and operating limits

- The request is an Adaptive Card webhook envelope, not the generic Power Automate
  HTTP-request schema.
- Simple notifications are supported; they are rendered as a card with no table.
- Structured tables are rendered as safe Adaptive Card column sets. Values are
  treated as text, never as HTML or executable card JSON.
- The provider bounds the complete webhook payload to 28,000 bytes and summarizes
  omitted rows or columns instead of truncating silently.
- Treat `UNKNOWN` delivery results as operator-review states. A timeout or lost
  response may mean the channel received the card; do not blindly resend with a
  new idempotency key.
- Teams webhook workflows may have tenant/channel restrictions. Validate the
  target channel, workflow owner, connection, and retention policy during release
  testing.

References: [Microsoft Teams incoming webhooks](https://learn.microsoft.com/en-us/microsoftteams/platform/webhooks-and-connectors/how-to/add-incoming-webhook)
and [Microsoft support for Teams webhook workflows](https://support.microsoft.com/en-us/workflows/send-messages-in-teams-using-incoming-webhooks).
