"""Tests for setting up and unloading the integration."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.fast_netatmo.const import DOMAIN

from .conftest import (
    MAIN_ID,
    OUTDOOR_ID,
    Clock,
    FakeNetatmo,
    error_response,
    make_token,
    setup_integration,
)


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry, netatmo: FakeNetatmo
) -> None:
    """The entry loads, polls each endpoint once and unloads."""
    assert init_integration.state is ConfigEntryState.LOADED
    assert netatmo.calls == {"homesdata": 1, "homestatus": 1, "getstationsdata": 1}

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.state is ConfigEntryState.NOT_LOADED


async def test_requests_use_form_post_and_bearer_token(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    aioclient_mock,
) -> None:
    """API calls are form-encoded POSTs with the access token."""
    status_calls = [
        c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/homestatus")
    ]
    _, _, data, headers = status_calls[0]
    assert data == {"home_id": "5f0000000000000000000002"}
    assert headers == {"Authorization": "Bearer mock-access-token"}


async def test_setup_auth_error_starts_reauth(
    hass: HomeAssistant,
    setup_credentials: None,
    netatmo: FakeNetatmo,
    clock: Clock,
    config_entry: MockConfigEntry,
) -> None:
    """A rejected token during setup asks the user to sign in again."""
    netatmo.queue("homesdata", error_response(403, 2, "Invalid access token"))
    await setup_integration(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_setup_not_ready_on_api_error(
    hass: HomeAssistant,
    setup_credentials: None,
    netatmo: FakeNetatmo,
    clock: Clock,
    config_entry: MockConfigEntry,
) -> None:
    """A temporary API error during setup retries later."""
    netatmo.queue("homesdata", error_response(500))
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_not_ready_when_first_poll_fails(
    hass: HomeAssistant,
    setup_credentials: None,
    netatmo: FakeNetatmo,
    clock: Clock,
    config_entry: MockConfigEntry,
) -> None:
    """Without any data yet, a failed first poll retries the setup."""
    netatmo.queue("homestatus", error_response(429, 26, "User usage reached"))
    await setup_integration(hass, config_entry)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_token_refresh_rejected_starts_reauth(
    hass: HomeAssistant,
    setup_credentials: None,
    netatmo: FakeNetatmo,
    clock: Clock,
    aioclient_mock,
) -> None:
    """An expired token whose refresh is rejected asks the user to sign in again."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="5f0000000000000000000001",
        data={"auth_implementation": DOMAIN, "token": make_token(expires_in=-10)},
    )
    entry.add_to_hass(hass)
    aioclient_mock.post("https://api.netatmo.com/oauth2/token", status=400)

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_token_refresh_stores_rotated_tokens(
    hass: HomeAssistant,
    setup_credentials: None,
    netatmo: FakeNetatmo,
    clock: Clock,
    aioclient_mock,
) -> None:
    """A refreshed token pair replaces the old one in the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="5f0000000000000000000001",
        data={"auth_implementation": DOMAIN, "token": make_token(expires_in=-10)},
    )
    entry.add_to_hass(hass)
    aioclient_mock.post(
        "https://api.netatmo.com/oauth2/token",
        json={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 10800,
        },
    )

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data["token"]["refresh_token"] == "new-refresh"
    status_calls = [
        c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/homestatus")
    ]
    assert status_calls[0][3] == {"Authorization": "Bearer new-access"}


async def test_token_refresh_transient_error_retries_setup(
    hass: HomeAssistant,
    setup_credentials: None,
    netatmo: FakeNetatmo,
    clock: Clock,
    aioclient_mock,
) -> None:
    """A temporary token endpoint failure is not an auth failure."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="5f0000000000000000000001",
        data={"auth_implementation": DOMAIN, "token": make_token(expires_in=-10)},
    )
    entry.add_to_hass(hass)
    aioclient_mock.post("https://api.netatmo.com/oauth2/token", status=503)

    await setup_integration(hass, entry)

    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert not hass.config_entries.flow.async_progress()


async def test_devices(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Each module is a device; radio modules are connected via the station."""
    main = device_registry.async_get_device_by_identifier(
        (DOMAIN, MAIN_ID), init_integration.entry_id
    )
    outdoor = device_registry.async_get_device_by_identifier(
        (DOMAIN, OUTDOOR_ID), init_integration.entry_id
    )
    assert main is not None
    assert outdoor is not None
    assert (main.name, main.manufacturer, main.model) == (
        "Weather Station",
        "Netatmo",
        "Smart Home Weather station",
    )
    assert (outdoor.name, outdoor.model) == ("Outdoor Module", "Smart Outdoor Module")
    assert outdoor.via_device_id == main.id
    assert main.via_device_id is None


async def test_remove_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Only devices of modules that left the account can be removed."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)

    main = device_registry.async_get_device_by_identifier(
        (DOMAIN, MAIN_ID), init_integration.entry_id
    )
    assert main is not None
    await client.send_json_auto_id(
        {
            "type": "config/device_registry/remove_config_entry",
            "config_entry_id": init_integration.entry_id,
            "device_id": main.id,
        }
    )
    assert not (await client.receive_json())["success"]

    gone = device_registry.async_get_or_create(
        config_entry_id=init_integration.entry_id,
        identifiers={(DOMAIN, "02:00:00:00:00:99")},
    )
    await client.send_json_auto_id(
        {
            "type": "config/device_registry/remove_config_entry",
            "config_entry_id": init_integration.entry_id,
            "device_id": gone.id,
        }
    )
    assert (await client.receive_json())["success"]


def test_no_deprecated_imports() -> None:
    """No module imports a name that Home Assistant marks as deprecated."""
    package = Path(__file__).parents[1] / "custom_components" / DOMAIN
    deprecated = [
        f"{path.name}: {node.module}.{alias.name}"
        for path in sorted(package.glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.split(".")[0] == "homeassistant"
        for alias in node.names
        if hasattr(import_module(node.module), f"_DEPRECATED_{alias.name}")
    ]
    assert not deprecated
