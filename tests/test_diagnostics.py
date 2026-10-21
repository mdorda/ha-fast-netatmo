"""Tests for diagnostics."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fast_netatmo.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import FakeNetatmo, error_response

PERSONAL = [
    "mock-access-token",
    "mock-refresh-token",
    "user@example.com",
    "My Home",
    "Living room",
    "Weather Station",
    "Outdoor Module",
    "Example City",
    "48.85",
    "Europe/Paris",
    "5f0000000000000000000001",
    "5f0000000000000000000002",
    "70:ee:50:00:00:01",
    "02:00:00:00:00:01",
    "1000000002",
]


async def test_diagnostics_redact_and_alias(
    hass: HomeAssistant, init_integration: MockConfigEntry, netatmo: FakeNetatmo
) -> None:
    """No token, e-mail, name, location or real ID appears; relations stay readable."""
    netatmo.queue("homestatus", error_response(429, 26, "User usage reached"))
    await init_integration.runtime_data.async_refresh()

    diagnostics = await async_get_config_entry_diagnostics(hass, init_integration)
    text = json.dumps(diagnostics)

    for value in PERSONAL:
        assert value not in text, value

    assert diagnostics["entry"]["unique_id"] == "**REDACTED_USER**"
    assert diagnostics["topology"] == {"homes": 1, "modules": ["NAMain", "NAModule1"]}
    assert diagnostics["coordinator"]["effective_interval"] == 30
    assert diagnostics["coordinator"]["last_error"]["code"] == 26

    home = diagnostics["raw"]["homesdata"]["body"]["homes"][0]
    assert home["id"] == "**REDACTED_HOME_1**"
    assert home["modules"][1]["bridge"] == "**REDACTED_MODULE_1**"
    status = diagnostics["raw"]["homestatus"]["**REDACTED_HOME_1**"]["body"]["home"]
    assert [m["id"] for m in status["modules"]] == [
        "**REDACTED_MODULE_1**",
        "**REDACTED_MODULE_2**",
    ]
    # Battery voltage stays available for debugging.
    assert status["modules"][1]["battery_level"] == 5604
    station = diagnostics["raw"]["getstationsdata"]["body"]["devices"][0]
    assert station["_id"] == "**REDACTED_MODULE_1**"
    assert station["home_id"] == "**REDACTED_HOME_1**"
