"""Tests for the API client and its error mapping."""

from __future__ import annotations

from datetime import timedelta
from email.utils import format_datetime
from typing import Any
from unittest.mock import Mock

from aiohttp import ClientConnectionError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    OAuth2TokenRequestConnectionError,
    OAuth2TokenRequestReauthError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)
from yarl import URL

from custom_components.fast_netatmo.api import (
    NetatmoApi,
    NetatmoAuthError,
    NetatmoConnectionError,
    NetatmoError,
    parse_retry_after,
    parse_stations_data,
    parse_topology,
)

from .conftest import (
    HOME_ID,
    MAIN_ID,
    OUTDOOR_ID,
    USER_ID,
    FakeNetatmo,
    error_response,
    exc_response,
    load,
)


async def token() -> str:
    """Return a fixed access token."""
    return "token"


@pytest.fixture
async def api(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> NetatmoApi:
    """Return a client with a fixed token, created after the HTTP mock."""
    return NetatmoApi(async_get_clientsession(hass), token)


async def test_parse_fixtures() -> None:
    """The real-account fixtures parse into topology, status and extras."""
    topology = parse_topology(load("homesdata.json"))
    assert topology.user_id == USER_ID
    assert topology.homes == {HOME_ID: "My Home"}
    assert set(topology.modules) == {MAIN_ID, OUTDOOR_ID}
    assert topology.modules[OUTDOOR_ID].bridge == MAIN_ID

    slow = parse_stations_data(load("getstationsdata.json"))
    assert slow[MAIN_ID] == {"temp_trend": "stable", "pressure_trend": "down"}
    assert slow[OUTDOOR_ID] == {"temp_trend": "down", "battery_percent": 78}


async def test_topology_without_user_id_falls_back_to_home() -> None:
    """Without a user ID, the first home ID identifies the account."""
    body = load("homesdata.json")
    del body["body"]["user"]
    assert parse_topology(body).user_id == HOME_ID


async def test_empty_responses() -> None:
    """Missing bodies parse as empty."""
    assert parse_topology({}).homes == {}
    assert parse_topology({}).user_id == ""
    assert parse_stations_data({}) == {}
    assert parse_stations_data({"body": {"devices": [{"modules": [{}]}]}}) == {}


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, None), ("", None), ("120", 120.0), ("-5", 0.0), ("soon", None)],
)
def test_parse_retry_after(value: str | None, expected: float | None) -> None:
    """Retry-After in seconds."""
    assert parse_retry_after(value) == expected


def test_parse_retry_after_date() -> None:
    """Retry-After as an HTTP date, also in the past."""
    future = format_datetime(dt_util.utcnow() + timedelta(seconds=120), usegmt=True)
    past = format_datetime(dt_util.utcnow() - timedelta(seconds=120), usegmt=True)
    assert 115 <= (parse_retry_after(future) or 0) <= 120
    assert parse_retry_after(past) == 0.0
    assert (parse_retry_after("Wed, 21 Oct 2099 07:28:00") or 0) >= 0


@pytest.mark.parametrize(
    ("response", "error", "code"),
    [
        (error_response(403, 2, "Invalid access token"), NetatmoAuthError, 2),
        (error_response(401, 3, "Access token expired"), NetatmoAuthError, 3),
        (error_response(403, -1, "Grant is invalid"), NetatmoAuthError, -1),
        (error_response(403, 30, "Invalid refresh token"), NetatmoAuthError, 30),
        (error_response(400, 21, "Invalid home_id"), NetatmoError, 21),
        (error_response(400, 10, "Missing home_id"), NetatmoError, 10),
        (
            error_response(429, 11, "Failed to enter concurrency limited section"),
            NetatmoError,
            11,
        ),
        (error_response(429, 26, "User usage reached"), NetatmoError, 26),
        (error_response(403, 26, "Maximum usage reached"), NetatmoError, 26),
        (error_response(500), NetatmoError, None),
    ],
)
async def test_error_mapping(
    api: NetatmoApi,
    netatmo: FakeNetatmo,
    response: AiohttpClientMockResponse,
    error: type[NetatmoError],
    code: int | None,
) -> None:
    """Errors are mapped by Netatmo code, not by HTTP status."""
    netatmo.queue("homestatus", response)
    with pytest.raises(NetatmoError) as raised:
        await api.async_get_home_status(HOME_ID)
    assert type(raised.value) is error
    assert raised.value.code == code
    assert raised.value.status == response.status


async def test_auth_error_without_code(
    hass: HomeAssistant, api: NetatmoApi, aioclient_mock: AiohttpClientMocker
) -> None:
    """An OAuth-style 401 without a Netatmo code is an auth error."""
    aioclient_mock.post(
        "https://api.netatmo.com/api/homestatus",
        status=401,
        json={"error": "invalid_token"},
    )
    with pytest.raises(NetatmoAuthError, match="invalid_token"):
        await api.async_get_home_status(HOME_ID)


async def test_retry_after_is_passed_on(api: NetatmoApi, netatmo: FakeNetatmo) -> None:
    """The Retry-After header travels with the error."""
    netatmo.queue("homestatus", error_response(429, 26, headers={"Retry-After": "42"}))
    with pytest.raises(NetatmoError) as raised:
        await api.async_get_home_status(HOME_ID)
    assert raised.value.retry_after == 42.0


@pytest.mark.parametrize(
    "response",
    [
        exc_response(TimeoutError()),
        exc_response(ClientConnectionError()),
        AiohttpClientMockResponse(
            "POST", URL("https://api.netatmo.com"), text="<html>"
        ),
        AiohttpClientMockResponse(
            "POST", URL("https://api.netatmo.com"), json=["list"]
        ),
    ],
)
async def test_connection_errors(
    api: NetatmoApi, netatmo: FakeNetatmo, response: AiohttpClientMockResponse
) -> None:
    """Timeouts, network errors and unusable bodies are connection errors."""
    netatmo.queue("homestatus", response)
    with pytest.raises(NetatmoConnectionError):
        await api.async_get_home_status(HOME_ID)


@pytest.mark.parametrize(
    ("raised", "error"),
    [
        (
            OAuth2TokenRequestReauthError(
                request_info=Mock(real_url="https://api.netatmo.com/oauth2/token"),
                history=(),
                status=400,
                domain="fast_netatmo",
            ),
            NetatmoAuthError,
        ),
        (
            OAuth2TokenRequestConnectionError(domain="fast_netatmo"),
            NetatmoConnectionError,
        ),
        (ClientConnectionError(), NetatmoConnectionError),
    ],
)
async def test_token_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    raised: Exception,
    error: type[NetatmoError],
) -> None:
    """Token refresh failures map to auth or connection errors."""

    async def failing_token() -> str:
        raise raised

    api = NetatmoApi(async_get_clientsession(hass), failing_token)
    with pytest.raises(error):
        await api.async_get_homes_data()
    assert api.calls_last_hour() == 0


async def test_calls_are_counted(api: NetatmoApi, netatmo: FakeNetatmo) -> None:
    """Every request counts toward the hourly guard."""
    body: dict[str, Any] = await api.async_get_homes_data()
    assert body["status"] == "ok"
    await api.async_get_stations_data()
    assert api.calls_last_hour() == 2
