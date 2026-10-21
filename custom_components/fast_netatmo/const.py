"""Constants for the Netatmo (fast weather) integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "fast_netatmo"
MANUFACTURER: Final = "Netatmo"
PLATFORMS: Final = [Platform.SENSOR]

API_URL: Final = "https://api.netatmo.com"
OAUTH2_AUTHORIZE: Final = f"{API_URL}/oauth2/authorize"
OAUTH2_TOKEN: Final = f"{API_URL}/oauth2/token"
SCOPE: Final = "read_station"

CONF_URL_WEATHER: Final = "https://my.netatmo.com/app/weather"

NA_MAIN: Final = "NAMain"
NA_MODULE_1: Final = "NAModule1"
NA_MODULE_2: Final = "NAModule2"
NA_MODULE_3: Final = "NAModule3"
NA_MODULE_4: Final = "NAModule4"
WEATHER_TYPES: Final = frozenset(
    {NA_MAIN, NA_MODULE_1, NA_MODULE_2, NA_MODULE_3, NA_MODULE_4}
)

# Same model names as the core integration (pyatmo DEVICE_DESCRIPTION_MAP).
MODEL_NAMES: Final = {
    NA_MAIN: "Smart Home Weather station",
    NA_MODULE_1: "Smart Outdoor Module",
    NA_MODULE_2: "Smart Anemometer",
    NA_MODULE_3: "Smart Rain Gauge",
    NA_MODULE_4: "Smart Indoor Module",
}

CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_GRACE_PERIOD: Final = "grace_period"
CONF_AUTO_RELOAD: Final = "auto_reload"

DEFAULT_SCAN_INTERVAL: Final = 30
MIN_SCAN_INTERVAL: Final = 10
MAX_SCAN_INTERVAL: Final = 600
DEFAULT_GRACE_PERIOD: Final = 5
MAX_GRACE_PERIOD: Final = 60
DEFAULT_AUTO_RELOAD: Final = True

# Each home is polled once per interval, so this keeps /homestatus at <= 360 calls/h.
SECONDS_PER_HOME: Final = 10

# /getstationsdata (trends, battery): Netatmo refreshes it every ~10 minutes.
SLOW_FETCH_INTERVAL: Final = 600

# Error backoff as a multiple of the interval, as in the previous code of this repo.
ERROR_PENALTY: Final = 2
SLOW_ERROR_PENALTY: Final = 3
MAX_RETRY_AFTER: Final = 3600

# Own calls-per-hour guard: above this rate, push the next poll back.
RATE_LIMIT_PER_HOUR: Final = 400
RATE_LIMIT_DELAY: Final = 60

# A topology change must show up in this many consecutive polls before reloading.
TOPOLOGY_CHANGE_POLLS: Final = 2
TOPOLOGY_RELOAD_COOLDOWN: Final = 3600

DEFAULT_TITLE: Final = "Netatmo (fast weather)"
