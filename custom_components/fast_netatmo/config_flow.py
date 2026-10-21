"""Config flow for the Netatmo (fast weather) integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.config_entries import (
    SOURCE_REAUTH,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client, config_entry_oauth2_flow
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import probatio

from .api import NetatmoApi, NetatmoAuthError, NetatmoError, parse_topology
from .const import (
    CONF_AUTO_RELOAD,
    CONF_GRACE_PERIOD,
    CONF_SCAN_INTERVAL,
    DEFAULT_AUTO_RELOAD,
    DEFAULT_GRACE_PERIOD,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TITLE,
    DOMAIN,
    MAX_GRACE_PERIOD,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SCOPE,
)
from .coordinator import FastNetatmoConfigEntry


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle the OAuth2 sign-in with the user's own Netatmo app."""

    DOMAIN = DOMAIN

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: FastNetatmoConfigEntry,
    ) -> OptionsFlowHandler:
        """Return the options flow."""
        return OptionsFlowHandler()

    @property
    def logger(self) -> logging.Logger:
        """Return the logger."""
        return logging.getLogger(__name__)

    @property
    def extra_authorize_data(self) -> dict[str, Any]:
        """Request read access to weather stations only."""
        return {"scope": SCOPE}

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after the authorization was rejected."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm reauthentication."""
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Identify the account and create or update the entry."""
        access_token: str = data["token"]["access_token"]

        async def get_access_token() -> str:
            return access_token

        api = NetatmoApi(
            aiohttp_client.async_get_clientsession(self.hass), get_access_token
        )
        try:
            topology = parse_topology(await api.async_get_homes_data())
        except NetatmoAuthError:
            return self.async_abort(reason="oauth_unauthorized")
        except NetatmoError:
            return self.async_abort(reason="cannot_connect")

        if not topology.user_id or not topology.homes:
            return self.async_abort(reason="no_devices_found")

        await self.async_set_unique_id(topology.user_id)
        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="wrong_account")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data=data
            )
        self._abort_if_unique_id_configured()

        # The e-mail address is never stored; the title uses the home names.
        title = ", ".join(name for name in topology.homes.values() if name)
        return self.async_create_entry(title=title or DEFAULT_TITLE, data=data)


class OptionsFlowHandler(OptionsFlowWithReload):
    """Polling options; saving them reloads the entry."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_GRACE_PERIOD: int(user_input[CONF_GRACE_PERIOD]),
                    CONF_AUTO_RELOAD: bool(user_input[CONF_AUTO_RELOAD]),
                }
            )

        options = self.config_entry.options
        schema = probatio.Schema(
            {
                probatio.Required(
                    CONF_SCAN_INTERVAL,
                    default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=1,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                probatio.Required(
                    CONF_GRACE_PERIOD,
                    default=options.get(CONF_GRACE_PERIOD, DEFAULT_GRACE_PERIOD),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0,
                        max=MAX_GRACE_PERIOD,
                        step=1,
                        unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                probatio.Required(
                    CONF_AUTO_RELOAD,
                    default=options.get(CONF_AUTO_RELOAD, DEFAULT_AUTO_RELOAD),
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
