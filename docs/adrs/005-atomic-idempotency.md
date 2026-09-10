# ADR 005: Atomic scoped idempotency

Status: accepted.

Keys are scoped by source application and channel. Atomic claim/wait/complete
prevents concurrent duplicate sends and detects content conflicts. Accepted and
known-failed results expire; unknown results require explicit operator resolution.
A future durable adapter must preserve these compare-and-set semantics.
