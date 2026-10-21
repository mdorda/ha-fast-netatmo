"""Diagnostics for the Netatmo (fast weather) integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import FastNetatmoConfigEntry

TO_REDACT = {
    "access_token",
    "refresh_token",
    "token",
    "email",
    "mail",
    "name",
    "module_name",
    "station_name",
    "home_name",
    "coordinates",
    "location",
    "place",
    "city",
    "altitude",
    "timezone",
    "title",
}


class _Aliases:
    """Replace real IDs with stable aliases, so relations stay readable."""

    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._counts: dict[str, int] = {}

    def add(self, real: str | None, kind: str) -> None:
        if not real or real in self._map:
            return
        if kind == "USER":
            self._map[real] = "**REDACTED_USER**"
            return
        self._counts[kind] = self._counts.get(kind, 0) + 1
        self._map[real] = f"**REDACTED_{kind}_{self._counts[kind]}**"

    def apply(self, data: Any) -> Any:
        if isinstance(data, dict):
            return {self.apply(k): self.apply(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.apply(v) for v in data]
        if isinstance(data, str):
            for real, alias in self._map.items():
                data = data.replace(real, alias)
            return data
        return data


def _collect_ids(aliases: _Aliases, raw: dict[str, Any]) -> None:
    homes_body = (raw.get("homesdata") or {}).get("body") or {}
    aliases.add((homes_body.get("user") or {}).get("id"), "USER")
    for home in homes_body.get("homes") or []:
        aliases.add(home.get("id"), "HOME")
        for room in home.get("rooms") or []:
            aliases.add(room.get("id"), "ROOM")
        for module in home.get("modules") or []:
            aliases.add(module.get("id"), "MODULE")
    for device in ((raw.get("getstationsdata") or {}).get("body") or {}).get(
        "devices"
    ) or []:
        aliases.add(device.get("home_id"), "HOME")
        aliases.add(device.get("_id"), "MODULE")
        for module in device.get("modules") or []:
            aliases.add(module.get("_id"), "MODULE")


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FastNetatmoConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    aliases = _Aliases()
    _collect_ids(aliases, coordinator.raw)
    # Entry data and the unique ID may contain IDs and tokens too.
    aliases.add(entry.unique_id, "USER")

    diagnostics = {
        "entry": {
            "options": dict(entry.options),
            "unique_id": entry.unique_id,
        },
        "coordinator": {
            "effective_interval": coordinator.base_interval,
            "current_interval": coordinator.update_interval.total_seconds()
            if coordinator.update_interval
            else None,
            "grace_period": coordinator.grace_period,
            "auto_reload": coordinator.auto_reload,
            "last_update_success": coordinator.last_update_success,
            "calls_last_hour": coordinator.api.calls_last_hour(),
            "last_error": coordinator.last_error,
        },
        "topology": {
            "homes": len(coordinator.topology.homes),
            "modules": sorted(m.type for m in coordinator.topology.modules.values()),
        },
        "raw": coordinator.raw,
    }
    return aliases.apply(async_redact_data(diagnostics, TO_REDACT))  # type: ignore[no-any-return]
