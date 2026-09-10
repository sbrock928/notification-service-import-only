# ADR 001: Import-only deployment

Status: accepted.

The library is invoked by an existing long-running user-session worker and sends
immediately. Queueing, scheduling, fan-out, hosted APIs, databases, and deployment
runtimes remain outside the package. This keeps current operations explicit and
avoids embedding a second application platform in a transport library.
