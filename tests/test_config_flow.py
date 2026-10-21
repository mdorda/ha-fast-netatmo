"""Tests for the config and options flows."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import config_entry_oauth2_flow
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.fast_netatmo.const import (
    CONF_AUTO_RELOAD,
    CONF_GRACE_PERIOD,
    CONF_SCAN_INTERVAL,
    DOMAIN,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
)

from .conftest import CLIENT_ID, USER_ID, Clock, FakeNetatmo, error_response

REDIRECT_URI = "https://example.com/auth/external/callback"

pytestmark = pytest.mark.usefixtures("current_request_with_host", "setup_credentials")


async def authorize(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Complete the OAuth redirect and return the flow result."""
    state = config_entry_oauth2_flow._encode_jwt(
        hass, {"flow_id": result["flow_id"], "redirect_uri": REDIRECT_URI}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"] == (
        f"{OAUTH2_AUTHORIZE}?response_type=code&client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&state={state}&scope=read_station"
    )
    client = await hass_client_no_auth()
    resp = await client.get(f"/auth/external/callback?code=abcd&state={state}")
    assert resp.status == 200

    aioclient_mock.post(
        OAUTH2_TOKEN,
        json={
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "expires_in": 10800,
            "scope": ["read_station"],
        },
    )
    with patch("custom_components.fast_netatmo.async_setup_entry", return_value=True):
        return await hass.config_entries.flow.async_configure(result["flow_id"])  # type: ignore[return-value]


async def start(hass: HomeAssistant) -> dict[str, Any]:
    """Start a user flow."""
    return await hass.config_entries.flow.async_init(  # type: ignore[return-value]
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_full_flow(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    netatmo: FakeNetatmo,
) -> None:
    """The account ID is the unique ID, the home name the title; no e-mail is stored."""
    result = await authorize(
        hass, hass_client_no_auth, aioclient_mock, await start(hass)
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.unique_id == USER_ID
    assert entry.title == "My Home"
    assert entry.data["token"]["refresh_token"] == "new-refresh-token"
    assert "user@example.com" not in repr(entry.as_dict())


async def test_title_with_several_homes(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    netatmo: FakeNetatmo,
) -> None:
    """Homes with a station are joined; homes without one are left out."""
    netatmo.second_home()
    result = await authorize(
        hass, hass_client_no_auth, aioclient_mock, await start(hass)
    )
    assert result["title"] == "My Home, Cottage"


async def test_title_fallback(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    netatmo: FakeNetatmo,
) -> None:
    """A home without a name gets the integration name as title."""
    netatmo.homesdata["body"]["homes"][0]["name"] = ""
    result = await authorize(
        hass, hass_client_no_auth, aioclient_mock, await start(hass)
    )
    assert result["title"] == "Netatmo (fast weather)"


async def test_already_configured(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    netatmo: FakeNetatmo,
    config_entry: MockConfigEntry,
) -> None:
    """The same account can't be added twice."""
    result = await authorize(
        hass, hass_client_no_auth, aioclient_mock, await start(hass)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ("no_station", "no_devices_found"),
        ("auth", "oauth_unauthorized"),
        ("error", "cannot_connect"),
    ],
)
async def test_abort(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    netatmo: FakeNetatmo,
    change: str,
    reason: str,
) -> None:
    """Accounts without a station and API errors abort the flow."""
    if change == "no_station":
        netatmo.homesdata["body"]["homes"][0]["modules"] = []
    elif change == "auth":
        netatmo.queue("homesdata", error_response(403, 2, "Invalid access token"))
    else:
        netatmo.queue("homesdata", error_response(503))
    result = await authorize(
        hass, hass_client_no_auth, aioclient_mock, await start(hass)
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason


async def test_reauth(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    netatmo: FakeNetatmo,
    config_entry: MockConfigEntry,
) -> None:
    """Signing in again with the same account updates the tokens."""
    result = await config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    with patch("custom_components.fast_netatmo.async_setup_entry", return_value=True):
        result = await authorize(hass, hass_client_no_auth, aioclient_mock, result)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data["token"]["access_token"] == "new-access-token"
    assert config_entry.title == "My Home"


async def test_reauth_wrong_account(
    hass: HomeAssistant,
    hass_client_no_auth: ClientSessionGenerator,
    aioclient_mock: AiohttpClientMocker,
    netatmo: FakeNetatmo,
    config_entry: MockConfigEntry,
) -> None:
    """Signing in with another account doesn't overwrite the tokens."""
    netatmo.homesdata["body"]["user"]["id"] = "5f00000000000000000000ff"
    result = await config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await authorize(hass, hass_client_no_auth, aioclient_mock, result)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert config_entry.data["token"]["access_token"] == "mock-access-token"


@pytest.mark.usefixtures("netatmo", "clock")
async def test_options_flow(hass: HomeAssistant, config_entry: MockConfigEntry) -> None:
    """Options are saved and reload the entry."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    defaults = {str(k): k.default() for k in schema}
    assert defaults == {
        CONF_SCAN_INTERVAL: 30,
        CONF_GRACE_PERIOD: 5,
        CONF_AUTO_RELOAD: True,
    }

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 15.0, CONF_GRACE_PERIOD: 0.0, CONF_AUTO_RELOAD: False},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_SCAN_INTERVAL: 15,
        CONF_GRACE_PERIOD: 0,
        CONF_AUTO_RELOAD: False,
    }
    coordinator = config_entry.runtime_data
    assert coordinator.update_interval.total_seconds() == 15
    assert coordinator.grace_period == 0
    assert coordinator.auto_reload is False


@pytest.mark.usefixtures("netatmo")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        (CONF_SCAN_INTERVAL, 9),
        (CONF_SCAN_INTERVAL, 601),
        (CONF_GRACE_PERIOD, 61),
        (CONF_GRACE_PERIOD, -1),
    ],
)
async def test_options_ranges(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    clock: Clock,
    field: str,
    value: int,
) -> None:
    """Values outside the allowed ranges are rejected."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    user_input = {CONF_SCAN_INTERVAL: 30, CONF_GRACE_PERIOD: 5, CONF_AUTO_RELOAD: True}
    user_input[field] = value
    with pytest.raises(InvalidData, match=field):
        await hass.config_entries.options.async_configure(result["flow_id"], user_input)
