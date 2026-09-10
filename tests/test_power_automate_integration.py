"""Opt-in schema-v2 acceptance check against a controlled Power Automate Flow."""

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
_HOST_SUFFIX = os.environ.get("NOTIFICATION_TEST_PA_HOST_SUFFIX")


@pytest.mark.integration
@pytest.mark.live
@pytest.mark.skipif(
    not _ENDPOINT or not _HOST_SUFFIX,
    reason="Set the explicit Power Automate integration-test endpoint and host suffix",
)
async def test_power_automate_schema_v2_acceptance() -> None:
    assert _ENDPOINT is not None
    assert _HOST_SUFFIX is not None
    provider = PowerAutomateTeamsProvider(
        {"contract-test": PowerAutomateWebhook(_ENDPOINT)},
        allowed_host_suffixes={_HOST_SUFFIX},
    )
    try:
        outcome = await provider.send(
            TeamsNotification(
                destination="contract-test",
                title="Notification service contract test",
                text="This is an explicitly requested schema-v2 integration test.",
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
