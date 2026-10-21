"""The Netatmo (fast weather) integration."""

from __future__ import annotations

from typing import cast

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client, config_entry_oauth2_flow
from homeassistant.helpers.device_registry import DeviceEntry

from .api import NetatmoApi, NetatmoAuthError, NetatmoError, parse_topology
from .const import DOMAIN, PLATFORMS
from .coordinator import FastNetatmoConfigEntry, FastNetatmoCoordinator
from .entity import async_register_devices


async def async_setup_entry(hass: HomeAssistant, entry: FastNetatmoConfigEntry) -> bool:
    """Set up Netatmo (fast weather) from a config entry."""
    implementation = (
        await config_entry_oauth2_flow.async_get_config_entry_implementation(
            hass, entry
        )
    )
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)

    async def get_access_token() -> str:
        await session.async_ensure_token_valid()
        return cast(str, session.token["access_token"])

    api = NetatmoApi(aiohttp_client.async_get_clientsession(hass), get_access_token)
    try:
        raw_homes_data = await api.async_get_homes_data()
    except NetatmoAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except NetatmoError as err:
        raise ConfigEntryNotReady(str(err)) from err

    topology = parse_topology(raw_homes_data)
    coordinator = FastNetatmoCoordinator(hass, entry, api, topology, raw_homes_data)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    async_register_devices(hass, entry, topology)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: FastNetatmoConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: FastNetatmoConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow removing a device only when its module is gone from the account."""
    modules = entry.runtime_data.topology.modules
    return not any(
        domain == DOMAIN and identifier in modules
        for domain, identifier in device_entry.identifiers
    )
