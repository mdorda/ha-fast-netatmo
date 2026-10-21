"""Thin async client for the Netatmo weather station API."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import logging
from time import monotonic
from typing import Any

from aiohttp import ClientError, ClientSession
from homeassistant.exceptions import (
    OAuth2TokenRequestBaseError,
    OAuth2TokenRequestReauthError,
)

from .const import API_URL, NA_MAIN, WEATHER_TYPES

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30

# Netatmo error codes, see https://dev.netatmo.com/apidocumentation/general.
# The HTTP status does not reliably match the documented one, so map by code.
AUTH_ERROR_CODES = frozenset({-1, 2, 3, 30})
INVALID_HOME_ID_CODE = 21


class NetatmoError(Exception):
    """A failed Netatmo API call."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Initialize the error."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.retry_after = retry_after


class NetatmoAuthError(NetatmoError):
    """The access or refresh token is invalid; the user must sign in again."""


class NetatmoConnectionError(NetatmoError):
    """No usable response: timeout, network error or invalid body."""


@dataclass(frozen=True)
class Module:
    """A weather station module from /homesdata."""

    id: str
    type: str
    name: str
    home_id: str
    bridge: str | None


@dataclass(frozen=True)
class Topology:
    """The weather stations of one Netatmo account."""

    user_id: str
    homes: dict[str, str]
    modules: dict[str, Module]


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header given in seconds or as an HTTP date."""
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def parse_topology(body: dict[str, Any]) -> Topology:
    """Return the homes with an NAMain and their weather modules."""
    data = body.get("body") or {}
    homes: dict[str, str] = {}
    modules: dict[str, Module] = {}
    for home in data.get("homes") or []:
        home_id = home.get("id")
        home_modules = [
            m
            for m in home.get("modules") or []
            if m.get("type") in WEATHER_TYPES and m.get("id")
        ]
        if not home_id or not any(m["type"] == NA_MAIN for m in home_modules):
            continue
        homes[home_id] = home.get("name") or ""
        for module in home_modules:
            modules[module["id"]] = Module(
                id=module["id"],
                type=module["type"],
                name=module.get("name") or "",
                home_id=home_id,
                bridge=module.get("bridge"),
            )
    user_id = (data.get("user") or {}).get("id") or next(iter(homes), "")
    return Topology(user_id=user_id, homes=homes, modules=modules)


def parse_home_status(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return the weather modules of a /homestatus response by module ID."""
    home = (body.get("body") or {}).get("home") or {}
    return {
        m["id"]: m
        for m in home.get("modules") or []
        if m.get("type") in WEATHER_TYPES and m.get("id")
    }


def parse_stations_data(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return trends and battery from /getstationsdata by module ID.

    Only these fields are taken; the measurements are older than /homestatus.
    """
    result: dict[str, dict[str, Any]] = {}
    for device in (body.get("body") or {}).get("devices") or []:
        dashboard = device.get("dashboard_data") or {}
        if device_id := device.get("_id"):
            result[device_id] = {
                "temp_trend": dashboard.get("temp_trend"),
                "pressure_trend": dashboard.get("pressure_trend"),
            }
        for module in device.get("modules") or []:
            if module_id := module.get("_id"):
                result[module_id] = {
                    "temp_trend": (module.get("dashboard_data") or {}).get(
                        "temp_trend"
                    ),
                    "battery_percent": module.get("battery_percent"),
                }
    return result


class NetatmoApi:
    """Netatmo API client on top of a token provider."""

    def __init__(
        self,
        websession: ClientSession,
        get_access_token: Callable[[], Awaitable[str]],
    ) -> None:
        """Initialize the client."""
        self._websession = websession
        self._get_access_token = get_access_token
        self._calls: deque[float] = deque()

    def calls_last_hour(self) -> int:
        """Return how many API calls this client made in the last hour."""
        cutoff = monotonic() - 3600
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()
        return len(self._calls)

    async def async_get_homes_data(self) -> dict[str, Any]:
        """Return the raw /homesdata response."""
        return await self._async_post("homesdata")

    async def async_get_home_status(self, home_id: str) -> dict[str, Any]:
        """Return the raw /homestatus response of one home."""
        return await self._async_post("homestatus", {"home_id": home_id})

    async def async_get_stations_data(self) -> dict[str, Any]:
        """Return the raw /getstationsdata response."""
        return await self._async_post("getstationsdata")

    async def _async_post(
        self, endpoint: str, params: dict[str, str] | None = None
    ) -> dict[str, Any]:
        try:
            token = await self._get_access_token()
        except OAuth2TokenRequestReauthError as err:
            raise NetatmoAuthError(f"Token refresh rejected: {err}") from err
        except (OAuth2TokenRequestBaseError, ClientError) as err:
            raise NetatmoConnectionError(f"Token refresh failed: {err}") from err

        self._calls.append(monotonic())
        start = monotonic()
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                async with self._websession.post(
                    f"{API_URL}/api/{endpoint}",
                    data=params or {},
                    headers={"Authorization": f"Bearer {token}"},
                ) as resp:
                    status = resp.status
                    retry_after = parse_retry_after(resp.headers.get("Retry-After"))
                    try:
                        body = await resp.json(content_type=None)
                    except ValueError:
                        body = None
        except TimeoutError as err:
            _LOGGER.debug("/%s timed out after %ss", endpoint, REQUEST_TIMEOUT)
            raise NetatmoConnectionError(f"/{endpoint} timed out") from err
        except ClientError as err:
            _LOGGER.debug("/%s failed: %s", endpoint, err)
            raise NetatmoConnectionError(f"/{endpoint} failed: {err}") from err

        _LOGGER.debug(
            "/%s returned HTTP %s in %.2fs", endpoint, status, monotonic() - start
        )

        error = body.get("error") if isinstance(body, dict) else None
        if status == 200 and isinstance(body, dict) and error is None:
            return body

        code: int | None = None
        message = f"HTTP {status}"
        if isinstance(error, dict):
            code = error.get("code") if isinstance(error.get("code"), int) else None
            message = f"{message}, code {code}: {error.get('message')}"
        elif isinstance(error, str):
            message = f"{message}: {error}"
        elif status == 200:
            raise NetatmoConnectionError(
                f"/{endpoint} returned an invalid body", status=status
            )

        is_auth = code in AUTH_ERROR_CODES or (code is None and status == 401)
        cls = NetatmoAuthError if is_auth else NetatmoError
        raise cls(
            f"/{endpoint}: {message}",
            status=status,
            code=code,
            retry_after=retry_after,
        )
