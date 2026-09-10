"""Compatibility imports for Outlook email providers."""

from notification_service.providers.microsoft_graph import GraphEmailProvider
from notification_service.providers.win32com import Win32OutlookEmailProvider

__all__ = ["GraphEmailProvider", "Win32OutlookEmailProvider"]
