# Testing

Normal CI tests do not require Microsoft credentials, SQL Server, Redis, or Docker. Use a fake provider and deterministic outcomes.

Live testing is a release gate, not a unit test. It requires an approved internal mailbox and verifies application permissions, shared-mailbox scoping, attachment upload behavior, internal recipient restrictions, Zscaler connectivity, and credential rotation.
