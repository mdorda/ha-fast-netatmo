"""Data update coordinator for the Netatmo (fast weather) integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import logging
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    INVALID_HOME_ID_CODE,
    NetatmoApi,
    NetatmoAuthError,
    NetatmoError,
    Topology,
    parse_home_status,
    parse_stations_data,
)
from .const import (
    CONF_AUTO_RELOAD,
    CONF_GRACE_PERIOD,
    CONF_SCAN_INTERVAL,
    DEFAULT_AUTO_RELOAD,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    ERROR_PENALTY,
    MAX_RETRY_AFTER,
    RATE_LIMIT_DELAY,
    RATE_LIMIT_PER_HOUR,
    SECONDS_PER_HOME,
    SLOW_ERROR_PENALTY,
    SLOW_FETCH_INTERVAL,
    TOPOLOGY_CHANGE_POLLS,
    TOPOLOGY_RELOAD_COOLDOWN,
)

_LOGGER = logging.getLogger(__name__)

# Keys read from /homestatus; anything else is logged once per module type, so
# users of untested modules can report what their station sends.
KNOWN_KEYS = frozenset(
    {
        "id",
        "type",
        "bridge",
        "ts",
        "last_seen",
        "reachable",
        "firmware_revision",
        "battery_state",
        "battery_level",
        "rf_state",
        "rf_strength",
        "wifi_state",
        "wifi_strength",
        "temperature",
        "humidity",
        "co2",
        "noise",
        "pressure",
        "absolute_pressure",
        "rain",
        "sum_rain_1",
        "sum_rain_24",
        "wind_strength",
        "wind_angle",
        "wind_gust",
        "wind_gust_angle",
    }
)

type FastNetatmoConfigEntry = ConfigEntry[FastNetatmoCoordinator]


@dataclass
class FastNetatmoData:
    """Latest values: /homestatus per module, /getstationsdata extras per module."""

    modules: dict[str, dict[str, Any]]
    slow: dict[str, dict[str, Any]] = field(default_factory=dict)


def effective_interval(scan_interval: int, n_homes: int) -> int:
    """Return the polling interval that keeps /homestatus within the budget."""
    return max(scan_interval, SECONDS_PER_HOME * n_homes)


class FastNetatmoCoordinator(DataUpdateCoordinator[FastNetatmoData]):
    """Poll /homestatus for all homes and /getstationsdata every 10 minutes."""

    config_entry: FastNetatmoConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FastNetatmoConfigEntry,
        api: NetatmoApi,
        topology: Topology,
        raw_homes_data: dict[str, Any],
    ) -> None:
        """Initialize the coordinator."""
        options = entry.options
        scan_interval = int(options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
        self.base_interval = effective_interval(scan_interval, len(topology.homes))
        if self.base_interval != scan_interval:
            _LOGGER.info(
                "Polling every %ss instead of %ss to stay within the API limit for %s homes",
                self.base_interval,
                scan_interval,
                len(topology.homes),
            )
        self.grace_period = 60 * int(
            options.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD)
        )
        self.auto_reload = bool(options.get(CONF_AUTO_RELOAD, DEFAULT_AUTO_RELOAD))
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=self.base_interval),
            always_update=False,
        )
        self.api = api
        self.topology = topology
        self.raw: dict[str, Any] = {"homesdata": raw_homes_data, "homestatus": {}}
        self.last_success: float | None = None
        self.last_error: dict[str, Any] | None = None
        self._slow: dict[str, dict[str, Any]] = {}
        self._slow_due = 0.0
        self._failures = 0
        self._change_polls = 0
        self._change_logged = False
        self._unknown_keys_logged: set[str] = set()

    async def _async_update_data(self) -> FastNetatmoData:
        modules: dict[str, dict[str, Any]] = {}
        try:
            for home_id in self.topology.homes:
                body = await self.api.async_get_home_status(home_id)
                self.raw["homestatus"][home_id] = body
                modules.update(parse_home_status(body))
        except NetatmoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NetatmoError as err:
            if err.code == INVALID_HOME_ID_CODE:
                self._check_topology(changed=True)
            return self._handle_error(err)

        self._check_topology(changed=set(modules) != set(self.topology.modules))
        self._log_unknown_keys(modules)
        await self._async_slow_fetch()

        if self._failures:
            _LOGGER.info("Netatmo API is reachable again")
        self._failures = 0
        self.last_error = None
        self.last_success = monotonic()
        self.update_interval = timedelta(seconds=self._guard(self.base_interval))
        return FastNetatmoData(modules=modules, slow=self._slow)

    def _handle_error(self, err: NetatmoError) -> FastNetatmoData:
        """Back off, and keep the last data while within the grace period."""
        self._failures += 1
        delay = float(ERROR_PENALTY * self.base_interval)
        if err.retry_after is not None:
            delay = max(delay, min(err.retry_after, MAX_RETRY_AFTER))
        delay = self._guard(delay)
        self.update_interval = timedelta(seconds=delay)
        self.last_error = {
            "message": str(err),
            "status": err.status,
            "code": err.code,
            "retry_after": err.retry_after,
            "next_attempt_in": delay,
        }
        log = _LOGGER.warning if self._failures == 1 else _LOGGER.debug
        log("Updating Netatmo data failed, retrying in %.0fs: %s", delay, err)

        if (
            self.data is not None
            and self.last_success is not None
            and monotonic() - self.last_success < self.grace_period
        ):
            return self.data
        raise UpdateFailed(str(err)) from err

    def _guard(self, delay: float) -> float:
        """Push the next poll back while our own call rate is too high."""
        calls = self.api.calls_last_hour()
        if calls > RATE_LIMIT_PER_HOUR:
            _LOGGER.debug("%s calls in the last hour, delaying next poll", calls)
            return delay + RATE_LIMIT_DELAY
        return delay

    async def _async_slow_fetch(self) -> None:
        """Fetch trends and battery; a failure keeps the previous values."""
        now = monotonic()
        if now < self._slow_due:
            return
        try:
            body = await self.api.async_get_stations_data()
        except NetatmoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NetatmoError as err:
            self._slow_due = now + SLOW_ERROR_PENALTY * self.base_interval
            _LOGGER.debug("Fetching trends and battery failed: %s", err)
            return
        self.raw["getstationsdata"] = body
        self._slow = parse_stations_data(body)
        self._slow_due = now + SLOW_FETCH_INTERVAL

    def _check_topology(self, *, changed: bool) -> None:
        """Reload the entry when modules appear or disappear."""
        if not changed:
            self._change_polls = 0
            self._change_logged = False
            return
        self._change_polls += 1
        if not self.auto_reload:
            if not self._change_logged:
                _LOGGER.warning(
                    "The weather station modules changed; reload the integration to update them"
                )
                self._change_logged = True
            return
        if self._change_polls < TOPOLOGY_CHANGE_POLLS:
            return
        reloads: dict[str, float] = self.hass.data.setdefault(f"{DOMAIN}_reloads", {})
        now = monotonic()
        last = reloads.get(self.config_entry.entry_id)
        if last is not None and now - last < TOPOLOGY_RELOAD_COOLDOWN:
            _LOGGER.debug("Modules changed, but the last reload was too recent")
            return
        reloads[self.config_entry.entry_id] = now
        _LOGGER.info("The weather station modules changed, reloading")
        self.hass.config_entries.async_schedule_reload(self.config_entry.entry_id)

    def _log_unknown_keys(self, modules: dict[str, dict[str, Any]]) -> None:
        for module in modules.values():
            module_type = module["type"]
            if module_type in self._unknown_keys_logged:
                continue
            self._unknown_keys_logged.add(module_type)
            if unknown := sorted(set(module) - KNOWN_KEYS):
                _LOGGER.debug("%s sent unmapped keys: %s", module_type, unknown)
