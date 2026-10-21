"""Fixtures for the Netatmo (fast weather) tests.

The Netatmo API is mocked at the HTTP level: every POST to api.netatmo.com goes
through FakeNetatmo, which answers from the JSON fixtures. The fixtures are
anonymized real responses (NAMain + NAModule1); the other module types are added
from pyatmo's fixtures by `full_station`.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Generator
import copy
import json
from pathlib import Path
import re
import time
from typing import Any
from unittest.mock import PropertyMock, patch

from homeassistant.components.application_credentials import (
    ClientCredential,
    async_import_client_credential,
)
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.fast_netatmo.const import DOMAIN

FIXTURES = Path(__file__).parent / "fixtures"

CLIENT_ID = "client-id"
CLIENT_SECRET = "client-secret"
USER_ID = "5f0000000000000000000001"
HOME_ID = "5f0000000000000000000002"
HOME_2_ID = "5f0000000000000000000003"
MAIN_ID = "70:ee:50:00:00:01"
OUTDOOR_ID = "02:00:00:00:00:01"
WIND_ID = "06:00:00:00:00:01"
RAIN_ID = "05:00:00:00:00:01"
INDOOR_ID = "03:00:00:00:00:01"
THERM_ID = "04:00:00:00:00:01"
MAIN_2_ID = "70:ee:50:00:00:02"

API = re.compile(r"^https://api\.netatmo\.com/api/")


def load(name: str) -> Any:
    """Return a JSON fixture."""
    return json.loads((FIXTURES / name).read_text())


def error_response(
    status: int,
    code: int | None = None,
    message: str = "error",
    headers: dict[str, str] | None = None,
) -> AiohttpClientMockResponse:
    """Return a Netatmo error response."""
    body = {"error": {"code": code, "message": message}} if code is not None else None
    return AiohttpClientMockResponse(
        "POST",
        URL("https://api.netatmo.com"),
        status=status,
        json=body,
        text=None if body is not None else "Internal error",
        headers=headers,
    )


def exc_response(exc: BaseException) -> AiohttpClientMockResponse:
    """Return a response that raises instead of answering."""
    return AiohttpClientMockResponse("POST", URL("https://api.netatmo.com"), exc=exc)


class FakeNetatmo:
    """Answers Netatmo API requests from fixtures, with queueable failures."""

    def __init__(self) -> None:
        """Load the real-account fixtures."""
        self.homesdata: dict[str, Any] = load("homesdata.json")
        self.homestatus: dict[str, dict[str, Any]] = {HOME_ID: load("homestatus.json")}
        self.stations: dict[str, Any] = load("getstationsdata.json")
        self.queued: defaultdict[str, list[AiohttpClientMockResponse]] = defaultdict(
            list
        )
        self.failing: dict[str, AiohttpClientMockResponse] = {}
        self.calls: Counter[str] = Counter()
        self.requests: list[tuple[str, dict[str, Any] | None]] = []

    def queue(self, endpoint: str, *responses: AiohttpClientMockResponse) -> None:
        """Answer the next calls of an endpoint with these responses."""
        self.queued[endpoint].extend(responses)

    async def handle(
        self, method: str, url: URL, data: dict[str, Any] | None
    ) -> AiohttpClientMockResponse:
        """Route one request."""
        endpoint = url.path.rsplit("/", 1)[-1]
        self.calls[endpoint] += 1
        self.requests.append((endpoint, data))
        if self.queued[endpoint]:
            return self.queued[endpoint].pop(0)
        if endpoint in self.failing:
            return self.failing[endpoint]
        if endpoint == "homesdata":
            body = self.homesdata
        elif endpoint == "homestatus":
            body = self.homestatus[(data or {})["home_id"]]
        elif endpoint == "getstationsdata":
            body = self.stations
        else:  # pragma: no cover
            raise AssertionError(f"unexpected endpoint {endpoint}")
        return AiohttpClientMockResponse(method, url, json=copy.deepcopy(body))

    # Helpers to change the account in tests.

    def status_module(self, module_id: str, home_id: str = HOME_ID) -> dict[str, Any]:
        """Return the /homestatus entry of a module for editing."""
        modules = self.homestatus[home_id]["body"]["home"]["modules"]
        return next(m for m in modules if m["id"] == module_id)

    def full_station(self) -> None:
        """Add an anemometer, rain gauge, indoor module and a thermostat."""
        home = self.homesdata["body"]["homes"][0]
        status = self.homestatus[HOME_ID]["body"]["home"]["modules"]
        station = self.stations["body"]["devices"][0]
        radio = {
            WIND_ID: ("NAModule2", "Wind Gauge"),
            RAIN_ID: ("NAModule3", "Rain Gauge"),
            INDOOR_ID: ("NAModule4", "Bedroom"),
        }
        for module_id, (module_type, name) in radio.items():
            home["modules"].append(
                {"id": module_id, "type": module_type, "name": name, "bridge": MAIN_ID}
            )
            station["modules"].append(
                {
                    "_id": module_id,
                    "type": module_type,
                    "module_name": name,
                    "battery_percent": 60,
                    "dashboard_data": {"temp_trend": "up"}
                    if module_type == "NAModule4"
                    else {},
                }
            )
        common = {
            "battery_state": "medium",
            "battery_level": 4916,
            "firmware_revision": 14,
            "rf_state": "full",
            "rf_strength": 56,
            "last_seen": 1792605716,
            "reachable": True,
            "bridge": MAIN_ID,
            "ts": 1792605460,
        }
        # Values from pyatmo's fixtures/homestatus_ac_home_id.json; wind keys from pyatmo#546.
        status.extend(
            [
                {
                    "id": WIND_ID,
                    "type": "NAModule2",
                    **common,
                    "wind_strength": 12,
                    "wind_angle": 95,
                    "wind_gust": 25,
                    "wind_gust_angle": 350,
                },
                {
                    "id": RAIN_ID,
                    "type": "NAModule3",
                    **common,
                    "rain": 0.3,
                    "sum_rain_1": 0.6,
                    "sum_rain_24": 2.4,
                },
                {
                    "id": INDOOR_ID,
                    "type": "NAModule4",
                    **common,
                    "rf_state": "very_low",
                    "temperature": 23.1,
                    "co2": 420,
                    "humidity": 38,
                },
                # A thermostat in the same home must be ignored.
                {
                    "id": THERM_ID,
                    "type": "NATherm1",
                    "reachable": True,
                    "boiler_status": False,
                },
            ]
        )
        home["modules"].append(
            {"id": THERM_ID, "type": "NATherm1", "name": "Thermostat"}
        )

    def second_home(self) -> None:
        """Add a second home with its own station and a home without a station."""
        homes = self.homesdata["body"]["homes"]
        homes.append(
            {
                "id": HOME_2_ID,
                "name": "Cottage",
                "modules": [
                    {"id": MAIN_2_ID, "type": "NAMain", "name": "Cottage Station"}
                ],
            }
        )
        homes.append(
            {
                "id": "5f0000000000000000000004",
                "name": "Office",
                "modules": [
                    {"id": "04:00:00:00:00:09", "type": "NATherm1", "name": "T"}
                ],
            }
        )
        self.homestatus[HOME_2_ID] = {
            "status": "ok",
            "body": {
                "home": {
                    "id": HOME_2_ID,
                    "modules": [
                        {
                            "id": MAIN_2_ID,
                            "type": "NAMain",
                            "ts": 1792605714,
                            "temperature": 18.0,
                            "humidity": 60,
                            "co2": 500,
                            "noise": 35,
                            "pressure": 1010.0,
                            "absolute_pressure": 990.0,
                            "wifi_state": "high",
                            "wifi_strength": 60,
                        }
                    ],
                }
            },
        }


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations in all tests."""


@pytest.fixture
def entity_registry_enabled_by_default() -> Generator[None]:
    """Create disabled-by-default entities as enabled."""
    with patch(
        "homeassistant.helpers.entity.Entity.entity_registry_enabled_default",
        new_callable=PropertyMock,
        return_value=True,
    ):
        yield


@pytest.fixture
def netatmo(aioclient_mock: AiohttpClientMocker) -> FakeNetatmo:
    """Mock the Netatmo API."""
    fake = FakeNetatmo()
    aioclient_mock.post(API, side_effect=fake.handle)
    return fake


@pytest.fixture
async def setup_credentials(hass: HomeAssistant) -> None:
    """Register the user's own Netatmo app as application credentials."""
    assert await async_setup_component(hass, "application_credentials", {})
    await async_import_client_credential(
        hass, DOMAIN, ClientCredential(CLIENT_ID, CLIENT_SECRET), DOMAIN
    )


def make_token(expires_in: float = 10800) -> dict[str, Any]:
    """Return a token as stored in the config entry."""
    return {
        "access_token": "mock-access-token",
        "refresh_token": "mock-refresh-token",
        "token_type": "Bearer",
        "expires_in": expires_in,
        "expires_at": time.time() + expires_in,
        "scope": ["read_station"],
    }


@pytest.fixture
def options() -> dict[str, Any]:
    """Return the entry options; override in tests."""
    return {}


@pytest.fixture
def config_entry(hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
    """Return a config entry for the fixture account."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=USER_ID,
        title="My Home",
        data={"auth_implementation": DOMAIN, "token": make_token()},
        options=options,
    )
    entry.add_to_hass(hass)
    return entry


class Clock:
    """A controllable replacement for time.monotonic in the integration."""

    def __init__(self) -> None:
        """Start at an arbitrary point."""
        self.now = 10_000.0

    def __call__(self) -> float:
        """Return the current time."""
        return self.now

    def tick(self, seconds: float) -> None:
        """Advance the clock."""
        self.now += seconds


@pytest.fixture
def clock() -> Generator[Clock]:
    """Control the monotonic clock of the coordinator and the API client."""
    fake = Clock()
    with (
        patch("custom_components.fast_netatmo.coordinator.monotonic", fake),
        patch("custom_components.fast_netatmo.api.monotonic", fake),
    ):
        yield fake


async def setup_integration(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Set up the config entry and wait until it is done."""
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
async def init_integration(
    hass: HomeAssistant,
    setup_credentials: None,
    netatmo: FakeNetatmo,
    clock: Clock,
    config_entry: MockConfigEntry,
) -> MockConfigEntry:
    """Set up the integration with the mocked API."""
    await setup_integration(hass, config_entry)
    return config_entry
