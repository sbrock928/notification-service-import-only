"""Real Outlook/Win32 COM smoke test.

Purpose:
    Prove that this Windows machine can send a real email through the locally
    signed-in Classic Outlook desktop profile using pywin32/win32com.

Requirements:
    - Windows
    - Classic Outlook desktop installed and configured
    - Python 3.13
    - pywin32 installed:
        python -m pip install pywin32

Example:
    python outlook_win32com_smoke_test.py ^
        --to you@contoso.com ^
        --account your.name@contoso.com

Notes:
    - If --account is omitted, Outlook uses its default sending account.
    - --send-as can be used for a shared mailbox / send-on-behalf scenario,
      assuming Outlook/Exchange permissions already allow it.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send one real email through Classic Outlook using win32com."
    )
    parser.add_argument(
        "--to",
        required=True,
        help="Recipient SMTP address.",
    )
    parser.add_argument(
        "--account",
        help="Optional Outlook account SMTP address to send through.",
    )
    parser.add_argument(
        "--send-as",
        dest="send_as",
        help="Optional shared mailbox / send-on-behalf SMTP address.",
    )
    parser.add_argument(
        "--subject",
        default="Win32 Outlook smoke test",
        help="Email subject.",
    )
    parser.add_argument(
        "--body",
        default=(
            "This is a real test email sent from Python through "
            "Classic Outlook using win32com."
        ),
        help="Plain-text email body.",
    )
    return parser.parse_args()


def find_account(application: object, smtp_address: str) -> object:
    accounts = application.Session.Accounts
    available: list[str] = []

    for index in range(1, int(accounts.Count) + 1):
        account = accounts.Item(index)
        address = str(account.SmtpAddress)
        available.append(address)

        if address.casefold() == smtp_address.casefold():
            return account

    raise RuntimeError(
        f"Outlook account {smtp_address!r} was not found. "
        f"Available accounts: {available}"
    )


def main() -> int:
    if sys.platform != "win32":
        print(
            "ERROR: This smoke test must be run on Windows with Classic Outlook.",
            file=sys.stderr,
        )
        return 2

    try:
        import pythoncom
        import win32com.client
    except ImportError:
        print(
            "ERROR: pywin32 is not installed. Run: python -m pip install pywin32",
            file=sys.stderr,
        )
        return 2

    args = parse_args()

    pythoncom.CoInitialize()
    try:
        print("Opening Classic Outlook through COM...")
        outlook = win32com.client.Dispatch("Outlook.Application")

        message = outlook.CreateItem(0)

        if args.account:
            account = find_account(outlook, args.account)
            message.SendUsingAccount = account
            print(f"Using Outlook account: {args.account}")
        else:
            print("Using Outlook's default sending account.")

        message.To = args.to
        message.Subject = args.subject
        message.Body = (
            f"{args.body}\n\n"
            f"Smoke-test timestamp: {datetime.now().astimezone().isoformat()}"
        )

        if args.send_as:
            message.SentOnBehalfOfName = args.send_as
            print(f"Requested send-as / on-behalf-of address: {args.send_as}")

        print(f"Sending real email to: {args.to}")
        message.Send()

        print("SUCCESS: Outlook accepted the message for sending.")
        print(
            "Verify the message appears in Sent Items and arrives in the "
            "recipient mailbox."
        )
        return 0

    except Exception as exc:
        print(f"FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
