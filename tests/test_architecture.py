from __future__ import annotations

import importlib
import sys

import notification_service


def test_root_api_is_deliberate_and_graph_is_experimental() -> None:
    expected = {
        "AllowedEmailDomainsPolicy",
        "Attachment",
        "ClientClosedError",
        "DeliveryErrorCode",
        "DeliveryResult",
        "DeliveryState",
        "EmailNotification",
        "IdempotencyConflict",
        "InMemoryIdempotencyStore",
        "NotificationClient",
        "NotificationError",
        "NotificationTable",
        "PowerAutomateTeamsProvider",
        "PowerAutomateWebhook",
        "Recipient",
        "RetryPolicy",
        "SyncNotificationClient",
        "TableRenderPolicy",
        "TeamsNotification",
        "ValidationError",
        "Win32OutlookEmailProvider",
    }
    assert set(notification_service.__all__) == expected
    assert "azure.identity" not in sys.modules
    graph = importlib.import_module("notification_service.experimental.graph")
    assert graph.GraphEmailProvider
    assert "azure.identity" not in sys.modules


def test_removed_compatibility_modules_are_absent() -> None:
    for module in (
        "notification_service.models",
        "notification_service.service",
        "notification_service.outlook",
        "notification_service.power_automate",
        "notification_service.providers.microsoft_graph",
    ):
        assert importlib.util.find_spec(module) is None
