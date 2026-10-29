"""Tests for polling, backoff, grace period, slow fetch and topology changes."""

from __future__ import annotations

from datetime import timedelta
from email.utils import format_datetime
import logging
from unittest.mock import patch

from aiohttp import ClientConnectionError
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fast_netatmo.const import (
    CONF_AUTO_RELOAD,
    CONF_GRACE_PERIOD,
    CONF_SCAN_INTERVAL,
)
from custom_components.fast_netatmo.coordinator import FastNetatmoCoordinator

from .conftest import (
    HOME_2_ID,
    HOME_ID,
    OUTDOOR_ID,
    Clock,
    FakeNetatmo,
    error_response,
    exc_response,
    setup_integration,
)

TEMPERATURE = "sensor.weather_station_temperature"
BATTERY = "sensor.outdoor_module_battery"


def coordinator_of(entry: MockConfigEntry) -> FastNetatmoCoordinator:
    """Return the entry's coordinator."""
    coordinator: FastNetatmoCoordinator = entry.runtime_data
    return coordinator


def interval(entry: MockConfigEntry) -> float:
    """Return the current polling interval in seconds."""
    current = coordinator_of(entry).update_interval
    assert current is not None
    return current.total_seconds()


async def refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Poll once."""
    await coordinator_of(entry).async_refresh()
    await hass.async_block_till_done()


def set_temperature(netatmo: FakeNetatmo, value: float) -> None:
    """Change the station's live temperature."""
    netatmo.status_module("70:ee:50:00:00:01")["temperature"] = value


async def test_default_interval(init_integration: MockConfigEntry) -> None:
    """The default interval is 30 s."""
    assert interval(init_integration) == 30


async def test_values_update(
    hass: HomeAssistant, init_integration: MockConfigEntry, netatmo: FakeNetatmo
) -> None:
    """Each poll reads fresh values from /homestatus."""
    set_temperature(netatmo, 24.2)
    await refresh(hass, init_integration)
    assert hass.states.get(TEMPERATURE).state == "24.2"


@pytest.mark.parametrize("options", [{CONF_SCAN_INTERVAL: 10}])
async def test_configured_interval(init_integration: MockConfigEntry) -> None:
    """The interval comes from the options."""
    assert interval(init_integration) == 10


@pytest.mark.parametrize("options", [{CONF_SCAN_INTERVAL: 10}])
async def test_interval_scales_with_homes(
    hass: HomeAssistant,
    setup_credentials: None,
    netatmo: FakeNetatmo,
    clock: Clock,
    config_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two homes need at least 20 s; a home without a station is not polled."""
    netatmo.second_home()
    await setup_integration(hass, config_entry)

    assert interval(config_entry) == 20
    assert "Polling every 20s instead of 10s" in caplog.text
    assert [d["home_id"] for e, d in netatmo.requests if e == "homestatus"] == [
        HOME_ID,
        HOME_2_ID,
    ]
    assert hass.states.get("sensor.cottage_station_temperature").state == "18.0"


@pytest.mark.parametrize(
    "failure",
    [
        error_response(429, 11, "Failed to enter concurrency limited section"),
        error_response(429, 26, "User usage reached"),
        error_response(403, 26, "Maximum usage reached"),
        error_response(429, 28, "Rate limit exceeded"),
        error_response(503),
        exc_response(TimeoutError()),
        exc_response(ClientConnectionError()),
    ],
)
async def test_error_backs_off_and_keeps_values(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    failure: object,
) -> None:
    """Any non-auth error waits 2x the interval and keeps the last values."""
    netatmo.queue("homestatus", failure)  # type: ignore[arg-type]
    await refresh(hass, init_integration)

    assert interval(init_integration) == 60
    assert hass.states.get(TEMPERATURE).state == "23.6"
    assert coordinator_of(init_integration).last_update_success

    set_temperature(netatmo, 24.0)
    await refresh(hass, init_integration)
    assert interval(init_integration) == 30
    assert hass.states.get(TEMPERATURE).state == "24.0"


async def test_repeated_errors_do_not_escalate(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    clock: Clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Backoff stays at 2x; only the first failure is a warning."""
    netatmo.failing["homestatus"] = error_response(503)
    with caplog.at_level(logging.DEBUG, logger="custom_components.fast_netatmo"):
        for _ in range(3):
            await refresh(hass, init_integration)
            assert interval(init_integration) == 60
            clock.tick(60)

    warnings = [
        r for r in caplog.records if "Updating Netatmo data failed" in r.message
    ]
    assert [r.levelno for r in warnings] == [
        logging.WARNING,
        logging.DEBUG,
        logging.DEBUG,
    ]

    del netatmo.failing["homestatus"]
    await refresh(hass, init_integration)
    assert "Netatmo API is reachable again" in caplog.text


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [("300", 300), ("5", 60), ("99999", 3600), ("soon", 60)],
)
async def test_retry_after(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    retry_after: str,
    expected: float,
) -> None:
    """Retry-After is honoured, at least 2x the interval and at most an hour."""
    netatmo.queue(
        "homestatus",
        error_response(
            429, 26, "User usage reached", headers={"Retry-After": retry_after}
        ),
    )
    await refresh(hass, init_integration)
    assert interval(init_integration) == expected


async def test_retry_after_http_date(
    hass: HomeAssistant, init_integration: MockConfigEntry, netatmo: FakeNetatmo
) -> None:
    """Retry-After may be an HTTP date."""
    when = format_datetime(dt_util.utcnow() + timedelta(seconds=600), usegmt=True)
    netatmo.queue("homestatus", error_response(429, 26, headers={"Retry-After": when}))
    await refresh(hass, init_integration)
    assert 595 <= interval(init_integration) <= 600


async def test_grace_period_expires(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    clock: Clock,
) -> None:
    """After 5 minutes without success, sensors become unavailable."""
    netatmo.failing["homestatus"] = error_response(503)
    clock.tick(299)
    await refresh(hass, init_integration)
    assert hass.states.get(TEMPERATURE).state == "23.6"

    clock.tick(2)
    await refresh(hass, init_integration)
    assert hass.states.get(TEMPERATURE).state == STATE_UNAVAILABLE
    assert interval(init_integration) == 60

    del netatmo.failing["homestatus"]
    await refresh(hass, init_integration)
    assert hass.states.get(TEMPERATURE).state == "23.6"


@pytest.mark.parametrize("options", [{CONF_GRACE_PERIOD: 0}])
async def test_no_grace_period(
    hass: HomeAssistant, init_integration: MockConfigEntry, netatmo: FakeNetatmo
) -> None:
    """With a grace period of 0, the first failure makes sensors unavailable."""
    netatmo.queue("homestatus", error_response(503))
    await refresh(hass, init_integration)
    assert hass.states.get(TEMPERATURE).state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    "failure",
    [
        error_response(403, 2, "Invalid access token"),
        error_response(401, 3, "Access token expired"),
        error_response(403, 30, "Invalid refresh token"),
    ],
)
async def test_auth_error_starts_reauth(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    failure: object,
) -> None:
    """Auth errors bypass the grace period and ask the user to sign in again."""
    netatmo.queue("homestatus", failure)  # type: ignore[arg-type]
    await refresh(hass, init_integration)

    assert not coordinator_of(init_integration).last_update_success
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


async def test_rate_guard(
    hass: HomeAssistant, init_integration: MockConfigEntry, clock: Clock
) -> None:
    """Above 400 own calls per hour, the next poll waits 60 s longer."""
    coordinator_of(init_integration).api._calls.extend([clock.now] * 400)
    await refresh(hass, init_integration)
    assert interval(init_integration) == 90


async def test_rate_guard_forgets_old_calls(
    hass: HomeAssistant, init_integration: MockConfigEntry, clock: Clock
) -> None:
    """Calls older than an hour don't count."""
    coordinator_of(init_integration).api._calls.extendleft([clock.now - 3601] * 400)
    await refresh(hass, init_integration)
    assert interval(init_integration) == 30


async def test_slow_fetch_every_ten_minutes(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    clock: Clock,
) -> None:
    """/getstationsdata is fetched at setup and then every 10 minutes."""
    clock.tick(599)
    await refresh(hass, init_integration)
    assert netatmo.calls["getstationsdata"] == 1

    netatmo.stations["body"]["devices"][0]["modules"][0]["battery_percent"] = 70
    clock.tick(1)
    await refresh(hass, init_integration)
    assert netatmo.calls["getstationsdata"] == 2
    assert hass.states.get(BATTERY).state == "70"


async def test_slow_fetch_failure_keeps_values(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    clock: Clock,
) -> None:
    """A failed slow fetch keeps battery and trends and retries after 3x the interval."""
    netatmo.queue("getstationsdata", error_response(503))
    set_temperature(netatmo, 25.0)
    clock.tick(600)
    await refresh(hass, init_integration)

    assert hass.states.get(TEMPERATURE).state == "25.0"
    assert hass.states.get(BATTERY).state == "78"
    assert interval(init_integration) == 30

    clock.tick(89)
    await refresh(hass, init_integration)
    assert netatmo.calls["getstationsdata"] == 2
    clock.tick(1)
    await refresh(hass, init_integration)
    assert netatmo.calls["getstationsdata"] == 3


async def test_slow_fetch_skipped_when_status_fails(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    clock: Clock,
) -> None:
    """During an outage only /homestatus is retried."""
    netatmo.queue("homestatus", error_response(503))
    clock.tick(600)
    await refresh(hass, init_integration)
    assert netatmo.calls["getstationsdata"] == 1


async def test_slow_fetch_auth_error_starts_reauth(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    clock: Clock,
) -> None:
    """An auth error in the slow fetch also asks the user to sign in again."""
    netatmo.queue("getstationsdata", error_response(403, 2, "Invalid access token"))
    clock.tick(600)
    await refresh(hass, init_integration)
    flows = hass.config_entries.flow.async_progress()
    assert [f["context"]["source"] for f in flows] == [SOURCE_REAUTH]


def add_module(netatmo: FakeNetatmo) -> None:
    """Make /homestatus report a module the topology doesn't know."""
    netatmo.homestatus[HOME_ID]["body"]["home"]["modules"].append(
        {
            "id": "03:00:00:00:00:42",
            "type": "NAModule4",
            "reachable": True,
            "temperature": 20,
        }
    )


async def test_new_module_reloads_after_two_polls(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    clock: Clock,
) -> None:
    """A topology change must persist for two polls; reloads are rate limited."""
    add_module(netatmo)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await refresh(hass, init_integration)
        reload.assert_not_called()
        await refresh(hass, init_integration)
        reload.assert_called_once_with(init_integration.entry_id)

        reload.reset_mock()
        clock.tick(3599)
        await refresh(hass, init_integration)
        reload.assert_not_called()
        clock.tick(1)
        await refresh(hass, init_integration)
        reload.assert_called_once_with(init_integration.entry_id)


async def test_removed_module_reloads(
    hass: HomeAssistant, init_integration: MockConfigEntry, netatmo: FakeNetatmo
) -> None:
    """A module that disappears also counts as a change."""
    modules = netatmo.homestatus[HOME_ID]["body"]["home"]["modules"]
    modules[:] = [m for m in modules if m["id"] != OUTDOOR_ID]
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await refresh(hass, init_integration)
        await refresh(hass, init_integration)
        reload.assert_called_once()


async def test_module_difference_is_logged(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The debug log names the types of new and missing modules, not their IDs."""
    modules = netatmo.homestatus[HOME_ID]["body"]["home"]["modules"]
    modules[:] = [m for m in modules if m["id"] != OUTDOOR_ID]
    add_module(netatmo)
    with caplog.at_level(logging.DEBUG, logger="custom_components.fast_netatmo"):
        await refresh(hass, init_integration)
    assert (
        "/homestatus differs from the known modules: "
        "new ['NAModule4'], missing ['NAModule1']"
    ) in caplog.text
    assert OUTDOOR_ID not in caplog.text


async def test_flapping_change_does_not_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry, netatmo: FakeNetatmo
) -> None:
    """A change seen only once is ignored."""
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        add_module(netatmo)
        await refresh(hass, init_integration)
        netatmo.homestatus[HOME_ID]["body"]["home"]["modules"].pop()
        await refresh(hass, init_integration)
        add_module(netatmo)
        await refresh(hass, init_integration)
        reload.assert_not_called()


async def test_invalid_home_id_reloads(
    hass: HomeAssistant, init_integration: MockConfigEntry, netatmo: FakeNetatmo
) -> None:
    """Code 21 (home removed) counts as a topology change."""
    netatmo.failing["homestatus"] = error_response(400, 21, "Invalid home_id")
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        await refresh(hass, init_integration)
        await refresh(hass, init_integration)
        reload.assert_called_once()


@pytest.mark.parametrize("options", [{CONF_AUTO_RELOAD: False}])
async def test_auto_reload_off(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    netatmo: FakeNetatmo,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """With auto-reload off, a change is only logged once."""
    add_module(netatmo)
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        for _ in range(3):
            await refresh(hass, init_integration)
        reload.assert_not_called()
    assert caplog.text.count("reload the integration to update them") == 1


async def test_real_reload_picks_up_new_module(
    hass: HomeAssistant, init_integration: MockConfigEntry, netatmo: FakeNetatmo
) -> None:
    """After the reload, the new module has entities."""
    netatmo.homesdata["body"]["homes"][0]["modules"].append(
        {
            "id": "03:00:00:00:00:42",
            "type": "NAModule4",
            "name": "Kids room",
            "bridge": "70:ee:50:00:00:01",
        }
    )
    add_module(netatmo)
    await refresh(hass, init_integration)
    await refresh(hass, init_integration)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.kids_room_temperature").state == "20"
