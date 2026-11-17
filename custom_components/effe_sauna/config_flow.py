"""Config flow for Effe ECC Sauna.

* search the sauna on the network (UDP 48899, like the app)
* enter the IP by hand
* associate a new sauna (or a sauna moved to another network / password)
  with the Wi-Fi: EspTouch, then SmartLink, from Home Assistant
* reconfigure: change the IP of an existing entry
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import selector

from . import DEFAULT_PORT, DOMAIN
from . import protocol as ccp
from .provisioning import ProvisionResult, provision

_LOGGER = logging.getLogger(__name__)

CONF_SSID = "ssid"
CONF_PASSWORD = "password"
CONF_BSSID = "bssid"
CONF_METHOD = "method"
CONF_DEVICE = "device"

MANUAL_SCHEMA = vol.Schema({
    vol.Required(CONF_HOST): str,
    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
})


def _probe(host: str, port: int) -> tuple[bool, str | None]:
    """(reachable, serial). Reachable if a STATE frame comes back, or at least
    the TCP port answers (the Effe app may be holding the controller)."""
    client = ccp.EccClient(host, port, connect_timeout=3, read_budget=2)
    try:
        client.request(ccp.CMD_GET_STATE, attempts=3)
    except ccp.ProtocolError:
        pass
    except OSError:
        return False, None
    try:
        return True, client.get_identity().serial
    except (OSError, ccp.ProtocolError):
        return True, None


class EffeSaunaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._found: dict[str, ccp.DiscoveredDevice] = {}
        self._wifi: dict[str, Any] = {}
        self._prov_task: asyncio.Task | None = None
        self._prov_result: ProvisionResult | None = None

    # ---------------------------------------------------------------- menu
    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id="user", menu_options=["discover", "manual", "wifi"])

    async def _create(self, host: str, port: int, errors: dict) -> Any:
        ok, serial = await self.hass.async_add_executor_job(_probe, host, port)
        if not ok:
            errors["base"] = "cannot_connect"
            return None
        await self.async_set_unique_id(f"effe_sauna_{serial}" if serial else f"effe_sauna_{host}")
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
        return self.async_create_entry(
            title=f"Effe Sauna ({host})", data={CONF_HOST: host, CONF_PORT: port}
        )

    # ------------------------------------------------------------ discover
    async def async_step_discover(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            dev = self._found[user_input[CONF_DEVICE]]
            if (res := await self._create(dev.host, DEFAULT_PORT, errors)) is not None:
                return res
        else:
            devs = await self.hass.async_add_executor_job(lambda: ccp.discover(timeout=3.0))
            configured = {e.data.get(CONF_HOST) for e in self._async_current_entries()}
            self._found = {d.mac: d for d in devs if d.host not in configured}
            if not self._found:
                return await self.async_step_manual(None, errors={"base": "no_devices"})
        options = [
            selector.SelectOptionDict(
                value=mac,
                label=f"{d.host} — seriale {d.serial}, firmware {d.firmware}",
            )
            for mac, d in self._found.items()
        ]
        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema({
                vol.Required(CONF_DEVICE): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options)
                )
            }),
            errors=errors,
        )

    # -------------------------------------------------------------- manual
    async def async_step_manual(self, user_input=None, errors: dict | None = None):
        errors = dict(errors or {})
        if user_input is not None:
            if (res := await self._create(user_input[CONF_HOST], user_input[CONF_PORT], errors)) is not None:
                return res
        schema = MANUAL_SCHEMA
        if self._prov_result is not None:
            schema = self.add_suggested_values_to_schema(
                MANUAL_SCHEMA, {CONF_HOST: self._prov_result.ip}
            )
        return self.async_show_form(step_id="manual", data_schema=schema, errors=errors)

    # ---------------------------------------------------------------- wifi
    async def async_step_wifi(self, user_input=None, errors: dict | None = None):
        errors = dict(errors or {})
        if user_input is not None:
            self._wifi = user_input
            return await self.async_step_wifi_run()
        schema = vol.Schema({
            vol.Required(CONF_SSID): str,
            vol.Optional(CONF_PASSWORD, default=""): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_BSSID): str,
            vol.Required(CONF_METHOD, default="auto"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=["auto", "esptouch", "smartlink"],
                    translation_key="method",
                )
            ),
        })
        if self._wifi:
            schema = self.add_suggested_values_to_schema(
                schema, {k: v for k, v in self._wifi.items() if k != CONF_PASSWORD}
            )
        return self.async_show_form(step_id="wifi", data_schema=schema, errors=errors)

    async def _run_provisioning(self) -> None:
        w = self._wifi
        self._prov_result = await self.hass.async_add_executor_job(
            lambda: provision(
                w[CONF_SSID], w.get(CONF_PASSWORD, ""), bssid=w.get(CONF_BSSID) or None,
                method=w.get(CONF_METHOD, "auto"),
            )
        )

    async def async_step_wifi_run(self, user_input=None):
        if self._prov_task is None:
            self._prov_result = None
            self._prov_task = self.hass.async_create_task(self._run_provisioning())
        if not self._prov_task.done():
            return self.async_show_progress(
                step_id="wifi_run", progress_action="provisioning",
                progress_task=self._prov_task,
            )
        task, self._prov_task = self._prov_task, None
        if task.exception() is not None:
            _LOGGER.warning("Wi-Fi provisioning failed: %r", task.exception())
            self._prov_result = None
        return self.async_show_progress_done(
            next_step_id="wifi_done" if self._prov_result else "wifi_failed"
        )

    async def async_step_wifi_failed(self, user_input=None):
        return await self.async_step_wifi(None, errors={"base": "no_answer"})

    async def async_step_wifi_done(self, user_input=None):
        res = self._prov_result
        assert res is not None
        errors: dict[str, str] = {}
        # Same serial as an existing entry: that entry follows the new IP
        # (_abort_if_unique_id_configured with updates) and the flow aborts.
        if (created := await self._create(res.ip, DEFAULT_PORT, errors)) is not None:
            return created
        return await self.async_step_manual(None, errors=errors)

    # -------------------------------------------------------- reconfigure
    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            ok, _serial = await self.hass.async_add_executor_job(
                _probe, user_input[CONF_HOST], user_input[CONF_PORT]
            )
            if ok:
                return self.async_update_reload_and_abort(
                    entry, data_updates=user_input,
                    title=f"Effe Sauna ({user_input[CONF_HOST]})",
                )
            errors["base"] = "cannot_connect"
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(MANUAL_SCHEMA, user_input or entry.data),
            errors=errors,
        )
