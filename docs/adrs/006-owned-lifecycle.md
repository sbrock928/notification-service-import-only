# ADR 006: Owned lifecycle

Status: accepted.

The async client owns one provider on one event loop, tracks invoked work, rejects
new work during close, and performs a bounded drain. The stable sync facade creates
the client on its private loop thread and contains no duplicate delivery logic.
Factories and shutdown must be exception-safe.
