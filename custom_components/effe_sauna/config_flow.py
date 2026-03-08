"""Config flow for Effe ECC Sauna."""
from __future__ import annotations

import asyncio
import socket
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT

from . import DEFAULT_PORT, DOMAIN

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
})


class EffeSaunaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            try:
                ok = await asyncio.wait_for(
                    self.hass.async_add_executor_job(self._test_connection, host, port),
                    timeout=6,
                )
                if ok:
                    await self.async_set_unique_id(f"effe_sauna_{host}")
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=f"Effe Sauna ({host})", data=user_input
                    )
                errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    def _test_connection(self, host: str, port: int) -> bool:
        try:
            with socket.create_connection((host, port), timeout=4):
                return True
        except OSError:
            return False
