# ADR 008: Python 3.13 and pip-only packaging

Status: accepted.

Version 0.1.0 supports Python 3.13 only and is distributed as a wheel through the
private feed. CI uses reviewed constraints, strict typing, branch coverage, wheel
import verification, and separate Windows installation of the Outlook extra.
