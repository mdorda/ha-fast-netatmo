"""Sensors for the Netatmo (fast weather) integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfPrecipitationDepth,
    UnitOfPressure,
    UnitOfRatio,
    UnitOfSoundPressure,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .api import Module
from .const import NA_MAIN, NA_MODULE_1, NA_MODULE_2, NA_MODULE_3, NA_MODULE_4
from .coordinator import FastNetatmoConfigEntry, FastNetatmoCoordinator
from .entity import FastNetatmoEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

DIRECTION_OPTIONS = ["n", "ne", "e", "se", "s", "sw", "w", "nw"]
TREND_OPTIONS = ["up", "down", "stable"]
SIGNAL_OPTIONS = ["very_low", "low", "medium", "high", "full"]

TEMPERATURE_MODULES = frozenset({NA_MAIN, NA_MODULE_1, NA_MODULE_4})
RADIO_MODULES = frozenset({NA_MODULE_1, NA_MODULE_2, NA_MODULE_3, NA_MODULE_4})
ALL_MODULES = RADIO_MODULES | {NA_MAIN}

type ValueFn = Callable[[dict[str, Any], dict[str, Any]], StateType | datetime]


@dataclass(frozen=True, kw_only=True)
class FastNetatmoSensorEntityDescription(SensorEntityDescription):
    """Describes a sensor of a weather station module."""

    module_types: frozenset[str]
    value_fn: ValueFn
    # Measurements go unavailable when the module is unreachable; diagnostics don't.
    measurement: bool = True


def _status(key: str) -> ValueFn:
    return lambda status, slow: status.get(key)


def _slow(key: str) -> ValueFn:
    return lambda status, slow: slow.get(key)


def _compass(key: str) -> ValueFn:
    def value(status: dict[str, Any], slow: dict[str, Any]) -> str | None:
        angle = status.get(key)
        if not isinstance(angle, (int, float)) or angle < 0:
            return None
        return DIRECTION_OPTIONS[int((angle % 360 + 22.5) // 45) % 8]

    return value


def _enum(key: str, options: list[str], source: Callable[[str], ValueFn]) -> ValueFn:
    get = source(key)

    def value(status: dict[str, Any], slow: dict[str, Any]) -> str | None:
        state = get(status, slow)
        if state is None:
            return None
        if state not in options:
            _LOGGER.debug("Unknown %s value: %s", key, state)
            return None
        return str(state)

    return value


def _timestamp(status: dict[str, Any], slow: dict[str, Any]) -> datetime | None:
    ts = status.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    return datetime.fromtimestamp(ts, UTC)


# Translation keys and enabled defaults follow the core integration, so names and
# therefore entity IDs match after migration. Sensors without a translation key take
# their name from the device class, as in core.
SENSOR_TYPES: tuple[FastNetatmoSensorEntityDescription, ...] = (
    FastNetatmoSensorEntityDescription(
        key="temperature",
        module_types=TEMPERATURE_MODULES,
        value_fn=_status("temperature"),
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    FastNetatmoSensorEntityDescription(
        key="humidity",
        module_types=TEMPERATURE_MODULES,
        value_fn=_status("humidity"),
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FastNetatmoSensorEntityDescription(
        key="co2",
        module_types=frozenset({NA_MAIN, NA_MODULE_4}),
        value_fn=_status("co2"),
        native_unit_of_measurement=UnitOfRatio.PARTS_PER_MILLION,
        device_class=SensorDeviceClass.CO2,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FastNetatmoSensorEntityDescription(
        key="noise",
        translation_key="noise",
        module_types=frozenset({NA_MAIN}),
        value_fn=_status("noise"),
        native_unit_of_measurement=UnitOfSoundPressure.DECIBEL,
        device_class=SensorDeviceClass.SOUND_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FastNetatmoSensorEntityDescription(
        key="pressure",
        module_types=frozenset({NA_MAIN}),
        value_fn=_status("pressure"),
        native_unit_of_measurement=UnitOfPressure.MBAR,
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    FastNetatmoSensorEntityDescription(
        key="absolute_pressure",
        translation_key="absolute_pressure",
        module_types=frozenset({NA_MAIN}),
        value_fn=_status("absolute_pressure"),
        native_unit_of_measurement=UnitOfPressure.MBAR,
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="temp_trend",
        translation_key="temp_trend",
        module_types=TEMPERATURE_MODULES,
        value_fn=_enum("temp_trend", TREND_OPTIONS, _slow),
        device_class=SensorDeviceClass.ENUM,
        options=TREND_OPTIONS,
        entity_registry_enabled_default=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="pressure_trend",
        translation_key="pressure_trend",
        module_types=frozenset({NA_MAIN}),
        value_fn=_enum("pressure_trend", TREND_OPTIONS, _slow),
        device_class=SensorDeviceClass.ENUM,
        options=TREND_OPTIONS,
        entity_registry_enabled_default=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="rain",
        module_types=frozenset({NA_MODULE_3}),
        value_fn=_status("rain"),
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FastNetatmoSensorEntityDescription(
        key="sum_rain_1",
        translation_key="sum_rain_1",
        module_types=frozenset({NA_MODULE_3}),
        value_fn=_status("sum_rain_1"),
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="sum_rain_24",
        translation_key="sum_rain_24",
        module_types=frozenset({NA_MODULE_3}),
        value_fn=_status("sum_rain_24"),
        native_unit_of_measurement=UnitOfPrecipitationDepth.MILLIMETERS,
        device_class=SensorDeviceClass.PRECIPITATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    FastNetatmoSensorEntityDescription(
        key="wind_strength",
        module_types=frozenset({NA_MODULE_2}),
        value_fn=_status("wind_strength"),
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    FastNetatmoSensorEntityDescription(
        key="wind_direction",
        translation_key="wind_direction",
        module_types=frozenset({NA_MODULE_2}),
        value_fn=_compass("wind_angle"),
        device_class=SensorDeviceClass.ENUM,
        options=DIRECTION_OPTIONS,
    ),
    FastNetatmoSensorEntityDescription(
        key="wind_angle",
        translation_key="wind_angle",
        module_types=frozenset({NA_MODULE_2}),
        value_fn=_status("wind_angle"),
        native_unit_of_measurement=DEGREE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        entity_registry_enabled_default=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="gust_strength",
        translation_key="gust_strength",
        module_types=frozenset({NA_MODULE_2}),
        value_fn=_status("wind_gust"),
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="gust_direction",
        translation_key="gust_direction",
        module_types=frozenset({NA_MODULE_2}),
        value_fn=_compass("wind_gust_angle"),
        device_class=SensorDeviceClass.ENUM,
        options=DIRECTION_OPTIONS,
        entity_registry_enabled_default=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="gust_angle",
        translation_key="gust_angle",
        module_types=frozenset({NA_MODULE_2}),
        value_fn=_status("wind_gust_angle"),
        native_unit_of_measurement=DEGREE,
        device_class=SensorDeviceClass.WIND_DIRECTION,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
        entity_registry_enabled_default=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="battery",
        module_types=RADIO_MODULES,
        value_fn=_slow("battery_percent"),
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        measurement=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="rf_strength",
        translation_key="rf_strength",
        module_types=RADIO_MODULES,
        value_fn=_enum("rf_state", SIGNAL_OPTIONS, _status),
        device_class=SensorDeviceClass.ENUM,
        options=SIGNAL_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        measurement=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="wifi_strength",
        translation_key="wifi_strength",
        module_types=frozenset({NA_MAIN}),
        value_fn=_enum("wifi_state", SIGNAL_OPTIONS, _status),
        device_class=SensorDeviceClass.ENUM,
        options=SIGNAL_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        measurement=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="reachable",
        translation_key="reachable",
        module_types=RADIO_MODULES,
        value_fn=_status("reachable"),
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        measurement=False,
    ),
    FastNetatmoSensorEntityDescription(
        key="last_measurement",
        translation_key="last_measurement",
        module_types=ALL_MODULES,
        value_fn=_timestamp,
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        measurement=False,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FastNetatmoConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors of all weather station modules."""
    coordinator = entry.runtime_data
    async_add_entities(
        FastNetatmoSensor(coordinator, module, description)
        for module in coordinator.topology.modules.values()
        for description in SENSOR_TYPES
        if module.type in description.module_types
    )


class FastNetatmoSensor(FastNetatmoEntity, SensorEntity):
    """A sensor of a weather station module."""

    entity_description: FastNetatmoSensorEntityDescription

    def __init__(
        self,
        coordinator: FastNetatmoCoordinator,
        module: Module,
        description: FastNetatmoSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, module)
        self.entity_description = description
        self._attr_unique_id = f"{module.id}-{description.key}"

    @property
    def _module_status(self) -> dict[str, Any] | None:
        return self.coordinator.data.modules.get(self.module.id)

    @property
    def available(self) -> bool:
        """Return whether the module reported data and, for measurements, is reachable."""
        status = self._module_status
        if not super().available or status is None:
            return False
        return (
            not self.entity_description.measurement
            or status.get("reachable") is not False
        )

    @property
    def native_value(self) -> StateType | datetime:
        """Return the current value."""
        status = self._module_status or {}
        slow = self.coordinator.data.slow.get(self.module.id, {})
        return self.entity_description.value_fn(status, slow)
