"""Devices and base entity for the Netatmo (fast weather) integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import Module, Topology
from .const import CONF_URL_WEATHER, DOMAIN, MANUFACTURER, MODEL_NAMES, NA_MAIN
from .coordinator import FastNetatmoConfigEntry, FastNetatmoCoordinator


@callback
def async_register_devices(
    hass: HomeAssistant, entry: FastNetatmoConfigEntry, topology: Topology
) -> None:
    """Register one device per module, stations first so modules can link to them."""
    registry = dr.async_get(hass)
    stations: dict[str, str] = {}
    for module in sorted(topology.modules.values(), key=lambda m: m.type != NA_MAIN):
        via_device_id = stations.get(module.bridge or "")
        device = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, module.id)},
            # Same device name as the core integration, so entity IDs match (README migration).
            name=module.name or MODEL_NAMES[module.type],
            manufacturer=MANUFACTURER,
            model=MODEL_NAMES[module.type],
            configuration_url=CONF_URL_WEATHER,
            via_device_id=via_device_id,
        )
        if module.type == NA_MAIN:
            stations[module.id] = device.id


class FastNetatmoEntity(CoordinatorEntity[FastNetatmoCoordinator]):
    """An entity of one weather station module."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: FastNetatmoCoordinator, module: Module) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self.module = module
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, module.id)})
