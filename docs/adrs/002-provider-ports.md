# ADR 002: Typed provider ports

Status: accepted.

Construct one typed `NotificationClient` per channel. Providers receive immutable
content and delivery metadata and return an internal accepted/failure outcome.
Provider-specific diagnostics do not enter the caller result. Infrastructure can
change through composition without changing notification construction.
