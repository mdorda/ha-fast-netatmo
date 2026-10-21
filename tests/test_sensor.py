"""Tests for the sensors."""

from __future__ import annotations

import logging

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import (
    INDOOR_ID,
    MAIN_ID,
    OUTDOOR_ID,
    RAIN_ID,
    THERM_ID,
    WIND_ID,
    Clock,
    FakeNetatmo,
    setup_integration,
)

pytestmark = pytest.mark.usefixtures("setup_credentials", "clock")


def entities_of(
    entity_registry: er.EntityRegistry, entry: MockConfigEntry
) -> dict[str, er.RegistryEntry]:
    """Return the entry's entities by entity ID."""
    return {
        e.entity_id: e
        for e in er.async_entries_for_config_entry(entity_registry, entry.entry_id)
    }


async def test_entities_of_real_station(
    hass: HomeAssistant,
    netatmo: FakeNetatmo,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """The fixture station gets core's entity IDs, unique IDs and enabled defaults."""
    await setup_integration(hass, config_entry)
    entities = entities_of(entity_registry, config_entry)

    enabled = {eid for eid, e in entities.items() if e.disabled_by is None}
    disabled = set(entities) - enabled
    assert enabled == {
        "sensor.weather_station_temperature",
        "sensor.weather_station_humidity",
        "sensor.weather_station_carbon_dioxide",
        "sensor.weather_station_noise",
        "sensor.weather_station_atmospheric_pressure",
        "sensor.outdoor_module_temperature",
        "sensor.outdoor_module_humidity",
        "sensor.outdoor_module_battery",
    }
    assert disabled == {
        "sensor.weather_station_absolute_pressure",
        "sensor.weather_station_temperature_trend",
        "sensor.weather_station_pressure_trend",
        "sensor.weather_station_wi_fi_strength",
        "sensor.weather_station_last_measurement",
        "sensor.outdoor_module_temperature_trend",
        "sensor.outdoor_module_rf_strength",
        "sensor.outdoor_module_reachability",
        "sensor.outdoor_module_last_measurement",
    }
    assert (
        entities["sensor.weather_station_temperature"].unique_id
        == f"{MAIN_ID}-temperature"
    )
    assert (
        entities["sensor.outdoor_module_battery"].unique_id == f"{OUTDOOR_ID}-battery"
    )

    assert hass.states.get("sensor.weather_station_temperature").state == "23.6"
    assert hass.states.get("sensor.weather_station_humidity").state == "45"
    assert hass.states.get("sensor.weather_station_carbon_dioxide").state == "707"
    assert hass.states.get("sensor.weather_station_noise").state == "51"
    assert (
        hass.states.get("sensor.weather_station_atmospheric_pressure").state == "1008.6"
    )
    assert hass.states.get("sensor.outdoor_module_temperature").state == "12.1"
    assert hass.states.get("sensor.outdoor_module_humidity").state == "82"
    # Battery comes from /getstationsdata, not from the coarse battery_state.
    assert hass.states.get("sensor.outdoor_module_battery").state == "78"


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_disabled_by_default_values(
    hass: HomeAssistant, netatmo: FakeNetatmo, config_entry: MockConfigEntry
) -> None:
    """Trends, signal, reachability and last measurement map correctly."""
    await setup_integration(hass, config_entry)

    states = {
        "sensor.weather_station_absolute_pressure": "980.7",
        "sensor.weather_station_temperature_trend": "stable",
        "sensor.weather_station_pressure_trend": "down",
        "sensor.weather_station_wi_fi_strength": "full",
        "sensor.weather_station_last_measurement": "2026-10-21T18:01:54+00:00",
        "sensor.outdoor_module_temperature_trend": "down",
        # Netatmo's own rf_state, not core's thresholds (which say "Medium" for 86).
        "sensor.outdoor_module_rf_strength": "low",
        "sensor.outdoor_module_reachability": "True",
        "sensor.outdoor_module_last_measurement": "2026-10-21T17:57:40+00:00",
    }
    for entity_id, state in states.items():
        assert hass.states.get(entity_id).state == state, entity_id


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_full_station(
    hass: HomeAssistant,
    netatmo: FakeNetatmo,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Anemometer, rain gauge and indoor module map; the thermostat is ignored."""
    netatmo.full_station()
    await setup_integration(hass, config_entry)

    states = {
        "sensor.wind_gauge_wind_speed": "12",
        "sensor.wind_gauge_wind_direction": "e",
        "sensor.wind_gauge_wind_angle": "95",
        "sensor.wind_gauge_gust_strength": "25",
        "sensor.wind_gauge_gust_direction": "n",
        "sensor.wind_gauge_gust_angle": "350",
        "sensor.wind_gauge_battery": "60",
        "sensor.rain_gauge_precipitation": "0.3",
        "sensor.rain_gauge_precipitation_last_hour": "0.6",
        "sensor.rain_gauge_precipitation_today": "2.4",
        "sensor.bedroom_temperature": "23.1",
        "sensor.bedroom_carbon_dioxide": "420",
        "sensor.bedroom_humidity": "38",
        "sensor.bedroom_temperature_trend": "up",
        "sensor.bedroom_rf_strength": "very_low",
    }
    for entity_id, state in states.items():
        assert hass.states.get(entity_id).state == state, entity_id

    unique_ids = {
        e.unique_id for e in entities_of(entity_registry, config_entry).values()
    }
    assert f"{WIND_ID}-gust_strength" in unique_ids
    assert f"{RAIN_ID}-sum_rain_24" in unique_ids
    assert f"{INDOOR_ID}-co2" in unique_ids
    assert not any(uid.startswith(THERM_ID) for uid in unique_ids)


async def test_full_station_enabled_defaults(
    hass: HomeAssistant,
    netatmo: FakeNetatmo,
    config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Enabled defaults of the radio modules follow core."""
    netatmo.full_station()
    await setup_integration(hass, config_entry)
    entities = entities_of(entity_registry, config_entry)

    def enabled(entity_id: str) -> bool:
        return entities[entity_id].disabled_by is None

    assert enabled("sensor.wind_gauge_wind_speed")
    assert enabled("sensor.wind_gauge_wind_direction")
    assert not enabled("sensor.wind_gauge_wind_angle")
    assert not enabled("sensor.wind_gauge_gust_strength")
    assert not enabled("sensor.wind_gauge_gust_direction")
    assert not enabled("sensor.wind_gauge_gust_angle")
    assert enabled("sensor.rain_gauge_precipitation")
    assert not enabled("sensor.rain_gauge_precipitation_last_hour")
    assert enabled("sensor.rain_gauge_precipitation_today")


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_missing_keys_are_unknown(
    hass: HomeAssistant,
    netatmo: FakeNetatmo,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A module without the expected keys shows unknown and logs what it sent."""
    netatmo.full_station()
    wind = netatmo.status_module(WIND_ID)
    del wind["wind_gust"], wind["wind_gust_angle"]
    wind["gust_strength"] = 30
    wind["wind_angle"] = -1
    netatmo.status_module(MAIN_ID)["wifi_state"] = "excellent"
    del netatmo.status_module(MAIN_ID)["ts"]
    del netatmo.stations["body"]["devices"][0]["dashboard_data"]["pressure_trend"]

    with caplog.at_level(logging.DEBUG, logger="custom_components.fast_netatmo"):
        await setup_integration(hass, config_entry)

    assert hass.states.get("sensor.wind_gauge_gust_strength").state == STATE_UNKNOWN
    assert hass.states.get("sensor.wind_gauge_gust_direction").state == STATE_UNKNOWN
    assert hass.states.get("sensor.wind_gauge_wind_direction").state == STATE_UNKNOWN
    assert (
        hass.states.get("sensor.weather_station_wi_fi_strength").state == STATE_UNKNOWN
    )
    assert (
        hass.states.get("sensor.weather_station_last_measurement").state
        == STATE_UNKNOWN
    )
    assert (
        hass.states.get("sensor.weather_station_pressure_trend").state == STATE_UNKNOWN
    )
    assert "NAModule2 sent unmapped keys: ['gust_strength']" in caplog.text
    assert "Unknown wifi_state value: excellent" in caplog.text


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_unreachable_module(
    hass: HomeAssistant, netatmo: FakeNetatmo, config_entry: MockConfigEntry
) -> None:
    """An unreachable module hides measurements but keeps diagnostics."""
    netatmo.status_module(OUTDOOR_ID)["reachable"] = False
    await setup_integration(hass, config_entry)

    assert (
        hass.states.get("sensor.outdoor_module_temperature").state == STATE_UNAVAILABLE
    )
    assert hass.states.get("sensor.outdoor_module_humidity").state == STATE_UNAVAILABLE
    assert (
        hass.states.get("sensor.outdoor_module_temperature_trend").state
        == STATE_UNAVAILABLE
    )
    assert hass.states.get("sensor.outdoor_module_battery").state == "78"
    assert hass.states.get("sensor.outdoor_module_rf_strength").state == "low"
    assert hass.states.get("sensor.outdoor_module_reachability").state == "False"
    assert (
        hass.states.get("sensor.outdoor_module_last_measurement").state
        != STATE_UNAVAILABLE
    )
    assert hass.states.get("sensor.weather_station_temperature").state == "23.6"


async def test_module_missing_from_status(
    hass: HomeAssistant,
    netatmo: FakeNetatmo,
    config_entry: MockConfigEntry,
    clock: Clock,
) -> None:
    """A module that /homestatus doesn't report is unavailable."""
    modules = netatmo.homestatus["5f0000000000000000000002"]["body"]["home"]["modules"]
    modules[:] = [m for m in modules if m["id"] != OUTDOOR_ID]
    await setup_integration(hass, config_entry)

    assert (
        hass.states.get("sensor.outdoor_module_temperature").state == STATE_UNAVAILABLE
    )
    assert hass.states.get("sensor.outdoor_module_battery").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.weather_station_temperature").state == "23.6"


@pytest.mark.parametrize(
    ("angle", "direction"),
    [
        (0, "n"),
        (22, "n"),
        (23, "ne"),
        (90, "e"),
        (180, "s"),
        (270, "w"),
        (337, "nw"),
        (338, "n"),
        (360, "n"),
    ],
)
@pytest.mark.usefixtures("entity_registry_enabled_by_default")
async def test_compass(
    hass: HomeAssistant,
    netatmo: FakeNetatmo,
    config_entry: MockConfigEntry,
    angle: int,
    direction: str,
) -> None:
    """Wind angles map to eight compass directions."""
    netatmo.full_station()
    netatmo.status_module(WIND_ID)["wind_angle"] = angle
    await setup_integration(hass, config_entry)
    assert hass.states.get("sensor.wind_gauge_wind_direction").state == direction


async def test_device_name_fallback(
    hass: HomeAssistant, netatmo: FakeNetatmo, config_entry: MockConfigEntry
) -> None:
    """A module without a name is named after its model."""
    netatmo.homesdata["body"]["homes"][0]["modules"][1]["name"] = ""
    await setup_integration(hass, config_entry)
    assert hass.states.get("sensor.smart_outdoor_module_temperature") is not None
