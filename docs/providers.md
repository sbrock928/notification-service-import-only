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

The adapter maps a logical destination to one deployment-owned complete workflow
webhook URL and emits the standard Teams webhook envelope with one Adaptive Card.
The URL's opaque query string is part of the secret; there is no separate
host-suffix configuration. The non-premium **Send webhook alerts to a channel**
workflow consumes this envelope and posts the card to its configured channel:

```json
{
  "type": "message",
  "attachments": [{
    "contentType": "application/vnd.microsoft.card.adaptive",
    "content": {
      "type": "AdaptiveCard",
      "version": "1.2",
      "body": [
        {"type": "TextBlock", "text": "Import exceptions", "weight": "Bolder"},
        {"type": "TextBlock", "text": "The import produced exception records.", "wrap": true}
      ]
    }
  }]
}
```

Simple messages still contain one card; tables are rendered as safe Adaptive Card
column sets and explicit omission summaries. The workflow owns the final channel
post action. Any `2xx` is webhook acceptance. Connect/pool failure is a
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
