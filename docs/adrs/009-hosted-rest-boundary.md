# ADR 009: Hosted REST boundary

Status: accepted for future design only.

Remote ingestion, if required, is a separately deployed API/application rather
than a runtime added to this import-only library. The API authenticates callers,
validates a versioned command, claims durable scoped idempotency, and returns
`202 Accepted` with an operation ID. A worker invokes this package's typed clients.

Queued/in-progress are job states. Accepted/failed/unknown are delivery states.
The API does not call providers directly, own business fan-out, accept provider
secrets or arbitrary templates, or replace the delivery idempotency semantics.
