"""Opt-in Teams webhook acceptance check against a controlled workflow."""

from __future__ import annotations

import os

import pytest

from notification_service import (
    NotificationTable,
    PowerAutomateTeamsProvider,
    PowerAutomateWebhook,
    TeamsNotification,
)
from notification_service.application import DeliveryMetadata, ProviderAccepted

_ENDPOINT = os.environ.get("NOTIFICATION_TEST_PA_SIGNED_URL")


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.skipif(
    not _ENDPOINT,
    reason="Set the full Power Automate integration-test signed URL",
)
async def test_power_automate_teams_webhook_acceptance() -> None:
    assert _ENDPOINT is not None
    provider = PowerAutomateTeamsProvider(
        {"contract-test": PowerAutomateWebhook(_ENDPOINT)},
    )
    try:
        outcome = await provider.send(
            TeamsNotification(
                destination="contract-test",
                title="Notification service contract test",
                text="This is an explicitly requested Teams webhook integration test.",
                tables=(
                    NotificationTable(
                        caption="Contract values",
                        columns=("Name", "Value"),
                        rows=(("schema", "2"),),
                    ),
                ),
            ),
            DeliveryMetadata(
                source_application="notification-contract-test",
                correlation_id="power-automate-contract-test",
                idempotency_key="power-automate-contract-test",
                channel="teams",
            ),
        )
    finally:
        await provider.aclose()
    assert isinstance(outcome, ProviderAccepted)
