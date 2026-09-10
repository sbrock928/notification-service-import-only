"""Real Microsoft Teams channel smoke test through Power Automate.

Purpose:
    Prove that Python can invoke the signed Power Automate HTTP-trigger URL used
    by notification-service-import-only and that the Flow can post the message
    into its configured Microsoft Teams channel.

Requirements:
    - Python 3.13
    - httpx installed:
        python -m pip install httpx
    - A Power Automate Flow with an HTTP trigger
    - The Flow must post the received content into the desired Teams channel

Recommended environment variables:
    NOTIFICATION_TEST_PA_SIGNED_URL
    NOTIFICATION_TEST_PA_HOST_SUFFIX

Example (PowerShell):
    $env:NOTIFICATION_TEST_PA_SIGNED_URL = "<signed Power Automate URL>"
    $env:NOTIFICATION_TEST_PA_HOST_SUFFIX = "logic.azure.com"

    python teams_channel_smoke_test.py --destination ops-alerts

Security:
    Never hard-code or commit the signed Power Automate URL. Treat it like a
    credential.

Important:
    HTTP 2xx proves that the Flow accepted the trigger request. The final proof
    of Teams delivery is seeing the message in the configured channel.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Post one real smoke-test notification to a Teams channel."
    )
    parser.add_argument(
        "--url",
        default=os.getenv("NOTIFICATION_TEST_PA_SIGNED_URL"),
        help=(
            "Signed Power Automate HTTP-trigger URL. Prefer the "
            "NOTIFICATION_TEST_PA_SIGNED_URL environment variable."
        ),
    )
    parser.add_argument(
        "--host-suffix",
        default=os.getenv("NOTIFICATION_TEST_PA_HOST_SUFFIX"),
        help=(
            "Approved host suffix for the signed URL, such as logic.azure.com. "
            "Prefer NOTIFICATION_TEST_PA_HOST_SUFFIX."
        ),
    )
    parser.add_argument(
        "--destination",
        default="teams-smoke-test",
        help="Logical destination name included in the schema-v2 payload.",
    )
    parser.add_argument(
        "--title",
        default="Python Teams smoke test",
        help="Message title.",
    )
    parser.add_argument(
        "--text",
        default="Python successfully invoked the Teams notification flow.",
        help="Message text.",
    )
    return parser.parse_args()


def validate_signed_url(url: str, allowed_host_suffix: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError("Power Automate URL must use HTTPS.")
    if not parsed.hostname:
        raise ValueError("Power Automate URL must contain a hostname.")
    if not parsed.query:
        raise ValueError("Expected a signed Power Automate URL with a query string.")

    hostname = parsed.hostname.casefold().rstrip(".")
    suffix = allowed_host_suffix.casefold().lstrip(".").rstrip(".")

    if hostname != suffix and not hostname.endswith("." + suffix):
        raise ValueError(
            f"URL host {hostname!r} does not match approved suffix {suffix!r}."
        )


def main() -> int:
    args = parse_args()

    if not args.url:
        print(
            "ERROR: Provide --url or set NOTIFICATION_TEST_PA_SIGNED_URL.",
            file=sys.stderr,
        )
        return 2

    if not args.host_suffix:
        print(
            "ERROR: Provide --host-suffix or set NOTIFICATION_TEST_PA_HOST_SUFFIX.",
            file=sys.stderr,
        )
        return 2

    try:
        validate_signed_url(args.url, args.host_suffix)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    correlation_id = str(uuid4())
    idempotency_key = f"teams-smoke-test:{uuid4()}"

    # Matches the schema-v2 payload used by notification-service-import-only.
    payload = {
        "schema_version": 2,
        "correlation_id": correlation_id,
        "idempotency_key": idempotency_key,
        "source_application": "manual-teams-smoke-test",
        "destination": args.destination,
        "title": args.title,
        "text": (
            f"{args.text}\n\n"
            f"UTC timestamp: {datetime.now(UTC).isoformat()}\n"
            f"Correlation ID: {correlation_id}"
        ),
        "tables": [],
    }

    try:
        print("Posting real notification to the Power Automate trigger...")

        with httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
            follow_redirects=False,
            trust_env=True,
        ) as client:
            response = client.post(args.url, json=payload)

        print(f"HTTP status: {response.status_code}")

        if 200 <= response.status_code < 300:
            print("SUCCESS: Power Automate accepted the request.")
            print(
                "Now verify that the message actually appeared in the configured "
                "Microsoft Teams channel."
            )
            return 0

        body_preview = response.text[:1000].replace("\n", " ")
        print(
            f"FAILED: Power Automate returned HTTP {response.status_code}.",
            file=sys.stderr,
        )
        if body_preview:
            print(f"Response preview: {body_preview}", file=sys.stderr)
        return 1

    except httpx.HTTPError as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
