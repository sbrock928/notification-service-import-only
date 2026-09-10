# ADR 004: Delivery certainty

Status: accepted.

Results are accepted, known failed, or unknown. Retry is permitted only after a
transient failure that proves non-acceptance. Timeouts, lost responses, and
post-invocation cancellation become unknown so the library cannot silently create
duplicate notifications.
