"""Real Microsoft Teams channel smoke test through Power Automate.

Purpose:
    Prove that Python can invoke the Teams webhook URL created by the
    Power Automate "Send webhook alerts to a channel" workflow and that the
    workflow can post the message into its configured channel.

Requirements:
    - Python 3.13
    - httpx installed:
        python -m pip install httpx
    - A Teams Workflows/Power Automate workflow created from
      "Send webhook alerts to a channel"

Corporate proxy and Zscaler setup (PowerShell):
    # Use the approved corporate proxy address. HTTPX honors these variables.
    $env:HTTPS_PROXY = "http://proxy.contoso.com:8080"
    $env:HTTP_PROXY = $env:HTTPS_PROXY
    $env:NO_PROXY = ""

    # Export the Zscaler root CA from certmgr.msc as Base-64 X.509 (.CER).
    # It must contain PEM text beginning with -----BEGIN CERTIFICATE-----.
    $env:SSL_CERT_FILE = "C:\ProgramData\Contoso\certs\zscaler-root.pem"

    # The library does not load .env files automatically. Set these variables
    # in the same PowerShell process that launches this script.

Recommended environment variables:
    NOTIFICATION_TEST_PA_SIGNED_URL

Example (PowerShell):
    $env:NOTIFICATION_TEST_PA_SIGNED_URL = "<signed Power Automate URL>"

    python teams_channel_smoke_test.py

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
            "Complete Teams workflow webhook URL. Prefer the "
            "NOTIFICATION_TEST_PA_SIGNED_URL environment variable."
        ),
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


def validate_signed_url(url: str) -> None:
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError("Power Automate URL must use HTTPS.")
    if not parsed.hostname:
        raise ValueError("Power Automate URL must contain a hostname.")
    if not parsed.query:
        raise ValueError("Expected a signed Power Automate URL with a query string.")


def main() -> int:
    args = parse_args()

    if not args.url:
        print(
            "ERROR: Provide --url or set NOTIFICATION_TEST_PA_SIGNED_URL.",
            file=sys.stderr,
        )
        return 2

    try:
        validate_signed_url(args.url)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    correlation_id = str(uuid4())

    # Matches the Adaptive Card envelope accepted by the Teams webhook trigger.
    payload = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": "Python Teams smoke test",
                            "weight": "Bolder",
                            "size": "Large",
                            "wrap": True,
                        },
                        {
                            "type": "TextBlock",
                            "text": (
                                f"{args.text}\n\n"
                                f"UTC timestamp: {datetime.now(UTC).isoformat()}\n"
                                f"Correlation ID: {correlation_id}"
                            ),
                            "wrap": True,
                        },
                    ],
                },
            }
        ],
    }

    try:
        print("Posting real notification to the Teams workflow webhook...")

        with httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
            follow_redirects=False,
            trust_env=True,
        ) as client:
            response = client.post(args.url, json=payload)

        print(f"HTTP status: {response.status_code}")

        if 200 <= response.status_code < 300:
            print("SUCCESS: Teams workflow accepted the webhook request.")
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
