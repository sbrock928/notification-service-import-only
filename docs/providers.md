# Provider contracts

## Classic Outlook email

The adapter runs all COM work in one dedicated serial executor, initializes COM on
that worker, resolves the configured profile account before creating mail, applies
the shared text/HTML table rendering, copies bounded attachments into private
temporary files, and calls `MailItem.Send()`.

Failures before `Send()` are known not accepted. Failures from `Send()` are
ambiguous. The package does not request delivery/read receipts. Setting
`SendUsingAccount` is expected to use that mailbox's Sent Items; Exchange policy
can affect shared-mailbox sent-copy behavior and must be checked manually.

## Power Automate Teams

The adapter maps a logical destination to a deployment-owned signed URL and emits
schema v2:

```json
{
  "schema_version": 2,
  "correlation_id": "corr-123",
  "idempotency_key": "teams:job:123",
  "source_application": "task-runner",
  "destination": "ops-alerts",
  "title": "Import exceptions",
  "text": "The import produced exception records.",
  "tables": [
    {
      "caption": "Exceptions",
      "columns": ["ID", "Reason"],
      "rows": [["1234", "Invalid status"]],
      "omitted_row_count": 0,
      "omitted_column_count": 0
    }
  ]
}
```

Simple messages contain `"tables": []`. The Flow validates v2 and owns final Teams
or Adaptive Card markup. Any `2xx` is trigger acceptance. Connect/pool failure is a
retryable non-acceptance; lost response, write/read error, 408, 5xx, and ordinary
429 are unknown. A deployment may opt into retryable 429 only with a documented
endpoint guarantee that throttling occurs before acceptance.

Power Automate does not provide end-to-end idempotency here. Disable unsafe Flow
retries or deduplicate at the Flow boundary.

## Experimental Graph

Graph email creates a draft, adds small or chunked attachments, sends it, and
best-effort deletes known orphan drafts. Only the send phase can mean email
acceptance. Upload URLs are restricted to approved Outlook hosts.

Graph Teams uses delegated `ChannelMessage.Send` and conservative escaped HTML.
It is research-only; supported formatting and permissions must be revalidated at
migration time. Graph providers are intentionally absent from the root API.
