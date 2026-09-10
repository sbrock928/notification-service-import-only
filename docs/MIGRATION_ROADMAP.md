# Migration roadmap

## Stage A — current 0.1.0

Run as an imported library in the existing worker. Classic Outlook delivers email;
Power Automate schema v2 delivers Teams notifications. Keep scheduling, queues,
business record selection, fan-out, and persistent audit history in host systems.

## Stage B — Graph email

Revalidate Graph APIs and permissions, configure an Entra application, restrict it
to the fixed mailbox through tenant/Exchange policy, and verify `Mail.ReadWrite`
plus `Mail.Send`. Run provider contract and live draft/attachment/send/orphan tests.
Change only provider composition after operational approval.

## Stage C — Teams transport decision

Revalidate whether ordinary unattended channel sends have an appropriate
application permission. If they still require delegated `ChannelMessage.Send`,
retain Power Automate or select another approved transport. Never use
`Teamwork.Migrate.All` for routine notifications.

## Stage D — optional hosted ingestion

If remote callers are later required, add a separate authenticated queue-first API
that returns `202 Accepted`. Queued and in-progress are job states; accepted,
failed, and unknown remain delivery states. Choose a durable atomic idempotency
adapter before horizontal scaling. Persistent delivery history is a separate audit
capability, not an idempotency store.
