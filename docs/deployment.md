# Deployment

Install the package into the existing upstream worker environment:

```bash
uv add notification-service-import-only
```

The worker process calls `await client.send(...)`; no second service process is required. If the upstream worker is synchronous, use `SyncNotificationClient` at the integration boundary.

Before production, run a controlled live test with an approved internal mailbox. Verify Power Automate HTTP-trigger authentication, flow ownership/co-ownership, shared-mailbox permissions, the Zscaler path, basic HTML/text mail, CSV/XLSX attachments, duplicate behavior when the flow response is lost, webhook rotation, and the behavior when the final provider response is lost.
