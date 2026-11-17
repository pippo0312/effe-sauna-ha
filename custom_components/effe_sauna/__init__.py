"""Effe ECC Sauna integration."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace as dataclass_replace
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import protocol as ccp
from .provisioning import provision

_LOGGER = logging.getLogger(__name__)

DOMAIN = "effe_sauna"
PLATFORMS = [Platform.SWITCH, Platform.SENSOR, Platform.BINARY_SENSOR, Platform.BUTTON]

DEFAULT_PORT = ccp.TCP_PORT
SCAN_INTERVAL = timedelta(seconds=5)

# Kept for backwards compatibility (v1.2.x imports).
CMD_STATUS = ccp.build_frame(ccp.CMD_GET_STATE)
CMD_ON = ccp.build_frame(ccp.CMD_ON, bytes((ccp.TARGET_SAUNA, ccp.FUNC_SAUNA)))
CMD_OFF = ccp.build_frame(ccp.CMD_OFF, bytes((ccp.TARGET_SAUNA, ccp.FUNC_SAUNA)))
CMD_LIGHT_ON = ccp.build_frame(ccp.CMD_ON, bytes((ccp.TARGET_SAUNA, ccp.FUNC_LIGHT)))
CMD_LIGHT_OFF = ccp.build_frame(ccp.CMD_OFF, bytes((ccp.TARGET_SAUNA, ccp.FUNC_LIGHT)))

# Consecutive failed polls before declaring the device unavailable. The Effe
# app holds an exclusive TCP connection while in use, so HA polls fail; the
# long grace avoids false "unavailable".
NO_DATA_THRESHOLD = 120  # ~600 s @ 5 s interval

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_SYNC_TIME = "sync_time"
SERVICE_WIFI_SETUP = "wifi_setup"
SERVICE_DISCOVER = "discover"


@dataclass
class SaunaData:
    available: bool
    master_on: bool = False
    light_on: bool = False
    ready: bool | None = None
    domotic: bool | None = None
    panel: bool | None = None
    sauna_flags: int | None = None
    # DATA[7] / frame[11]: controller probe, same scale as the setpoint
    # (2 units per °C). Settles on the setpoint while regulating; not
    # accurate when cold.
    heater_raw: int | None = None
    setpoint: float | None = None      # (DATA[16] & 0xFE) / 2


@dataclass
class DeviceInfoData:
    firmware: str | None = None
    serial: str | None = None
    product_code: int | None = None
    product_name: str | None = None
    wifi_firmware: str | None = None
    mac: str | None = None


def device_info(coordinator: "SaunaCoordinator") -> dict:
    info = coordinator.device
    model = "ECC"
    if info.product_name:
        model = f"ECC — {info.product_name} (codice {info.product_code})"
    dev = {
        "identifiers": {(DOMAIN, coordinator.entry_id)},
        "name": "Effe ECC Sauna",
        "manufacturer": "Effe Perfect Wellness",
        "model": model,
    }
    if info.firmware:
        dev["sw_version"] = info.firmware
    if info.wifi_firmware:
        dev["hw_version"] = f"Wi-Fi {info.wifi_firmware}"
    if info.serial:
        dev["serial_number"] = info.serial
    if info.mac:
        dev["connections"] = {(CONNECTION_NETWORK_MAC, info.mac.lower())}
    return dev


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    async def _discover(call: ServiceCall):
        hosts = call.data.get("hosts") or []
        devs = await hass.async_add_executor_job(
            lambda: ccp.discover(timeout=3.0, targets=["255.255.255.255", *hosts])
        )
        return {"devices": [d.__dict__ for d in devs]}

    async def _wifi_setup(call: ServiceCall):
        ssid = call.data["ssid"]
        password = call.data.get("password", "")
        bssid = call.data.get("bssid")
        method = call.data.get("method", "auto")
        _LOGGER.info("Effe ECC: Wi-Fi provisioning for '%s' (%s), 45-90 s", ssid, method)
        try:
            res = await hass.async_add_executor_job(
                lambda: provision(ssid, password, bssid=bssid, method=method)
            )
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        if res is None:
            raise HomeAssistantError(
                "Nessuna risposta dal modulo Wi-Fi: verifica che il led REMOTE "
                "lampeggi (2 volte CHANGE, poi on/off premuto 5 s) e che la rete "
                "sia a 2,4 GHz"
            )
        # Follow the new address if one of our entries matches the MAC.
        for coord in hass.data.get(DOMAIN, {}).values():
            if coord.device.mac and coord.device.mac.upper() == res.mac.upper() \
                    and coord.host != res.ip:
                entry = hass.config_entries.async_get_entry(coord.entry_id)
                if entry is not None:
                    hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_HOST: res.ip}
                    )
                    hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
        return {"method": res.method, "mac": res.mac, "ip": res.ip}

    async def _sync_time(call: ServiceCall) -> None:
        for coord in list(hass.data.get(DOMAIN, {}).values()):
            await coord.async_sync_time()

    hass.services.async_register(
        DOMAIN, SERVICE_DISCOVER, _discover,
        schema=vol.Schema({vol.Optional("hosts"): vol.All(cv.ensure_list, [cv.string])}),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_WIFI_SETUP, _wifi_setup,
        schema=vol.Schema({
            vol.Required("ssid"): cv.string,
            vol.Optional("password", default=""): cv.string,
            vol.Optional("bssid"): cv.string,
            vol.Optional("method", default="auto"): vol.In(["auto", "esptouch", "smartlink"]),
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_SYNC_TIME, _sync_time)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = SaunaCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    await coordinator.async_load_device_info()
    serial = coordinator.device.serial
    if serial and entry.unique_id != f"effe_sauna_{serial}" and not any(
        e.unique_id == f"effe_sauna_{serial}"
        for e in hass.config_entries.async_entries(DOMAIN)
    ):
        # v1.2.x used the IP as unique id: move to the serial, so that a new
        # IP (another network, DHCP) is recognised as the same sauna.
        hass.config_entries.async_update_entry(entry, unique_id=f"effe_sauna_{serial}")
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class SaunaCoordinator(DataUpdateCoordinator[SaunaData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.entry_id = entry.entry_id
        self.host = entry.data[CONF_HOST]
        self.port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self.client = ccp.EccClient(self.host, self.port)
        self.no_data_streak: int = 0
        self.device = DeviceInfoData()
        # Serialise TCP access: the controller accepts one client at a time.
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ poll
    async def _async_update_data(self) -> SaunaData:
        try:
            async with self._lock:
                data = await asyncio.wait_for(
                    self.hass.async_add_executor_job(self._query_status), timeout=4
                )
            if data.available:
                self.no_data_streak = 0
            else:
                self.no_data_streak += 1
            return data
        except asyncio.TimeoutError:
            # The socket work is bounded below this budget; if a poll still
            # overruns (app/panel holding the socket) keep the last state.
            self.no_data_streak += 1
            return self.data if self.data is not None else SaunaData(available=True)
        except Exception as err:  # noqa: BLE001
            self.no_data_streak += 1
            raise UpdateFailed(f"Communication error: {err!r}") from err

    def _keep_last(self, reachable: bool) -> SaunaData:
        if self.data is not None:
            return dataclass_replace(self.data, available=True)
        return SaunaData(available=reachable)

    def _query_status(self) -> SaunaData:
        # Total socket budget (connect 1.5 s + read 1.5 s) stays below the
        # 4 s asyncio budget, so a busy device gives a caught OSError.
        try:
            raw = self.client.exchange(CMD_STATUS, until_cmd=ccp.CMD_GET_STATE)
        except ConnectionResetError:
            # The device resets connections while the Effe app holds the socket.
            return self._keep_last(True)
        except OSError:
            return self._keep_last(False)

        _LOGGER.debug("status raw(%d): %s", len(raw), raw.hex())
        state = None
        for frame in ccp.parse_frames(raw):
            if frame.cmd == ccp.CMD_GET_STATE and len(frame.data) >= 25:
                if not frame.checksum_ok:
                    _LOGGER.debug("STATE frame with bad checksum ignored: %s", raw.hex())
                    continue
                state = ccp.parse_state(frame.data)
        if state is None:
            # Unsolicited ack only, or reply split across reads: keep last state.
            return self._keep_last(True)
        return SaunaData(
            available=True,
            master_on=state.on,
            light_on=state.light,
            ready=state.ready,
            domotic=state.domotic,
            panel=state.panel,
            sauna_flags=state.sauna_flags,
            heater_raw=state.probe_raw,
            setpoint=state.target_c,
        )

    # ------------------------------------------------------------ identity
    def _read_device_info(self) -> DeviceInfoData:
        info = DeviceInfoData()
        try:
            ident = self.client.get_identity()
            info.firmware = ident.firmware
            info.serial = ident.serial
            info.product_code = ident.product_code
            info.product_name = ident.product_name
        except (OSError, ccp.ProtocolError) as err:
            _LOGGER.debug("GET_IDENTITY failed: %s", err)
        try:
            info.wifi_firmware = self.client.get_wifi_firmware()
        except (OSError, ccp.ProtocolError) as err:
            _LOGGER.debug("GET_PARAM 28 failed: %s", err)
        try:
            mac = self.client.get_param(ccp.PARAM_MAC)
            if mac and len(mac) >= 7 and mac[0] == ccp.PARAM_MAC:
                info.mac = ":".join(f"{b:02X}" for b in mac[1:7])
        except (OSError, ccp.ProtocolError) as err:
            _LOGGER.debug("GET_PARAM 30 failed: %s", err)
        return info

    async def async_load_device_info(self) -> None:
        """Firmware, serial, product code, Wi-Fi module version (once per
        setup; failures are not fatal, the next reload retries)."""
        async with self._lock:
            try:
                self.device = await asyncio.wait_for(
                    self.hass.async_add_executor_job(self._read_device_info), timeout=30
                )
            except asyncio.TimeoutError:
                _LOGGER.debug("device info read timed out")

    # ------------------------------------------------------------ commands
    async def async_switch(self, function: int, on: bool) -> None:
        predicted = None
        if self.data is not None:
            if function == ccp.FUNC_SAUNA:
                predicted = dataclass_replace(
                    self.data, master_on=on, **({} if on else {"light_on": False})
                )
            elif function == ccp.FUNC_LIGHT:
                predicted = dataclass_replace(self.data, light_on=on)
        try:
            async with self._lock:
                await asyncio.wait_for(
                    self.hass.async_add_executor_job(self.client.switch, function, on),
                    timeout=12,
                )
        except ccp.CommandRejected as err:
            raise HomeAssistantError(
                "La sauna ha rifiutato il comando: abilita la domotica sul pannello"
            ) from err
        except (OSError, ccp.ProtocolError, asyncio.TimeoutError) as err:
            # The controller sometimes closes the socket right after executing
            # the command without answering: let the next poll decide.
            _LOGGER.warning("Effe ECC: command 0x%02X not confirmed: %r", function, err)
            await self.async_request_refresh()
            return
        if predicted is not None:
            self.async_set_updated_data(predicted)

    async def async_send_command(self, cmd: bytes) -> bool:
        """v1.2.x API, kept for compatibility."""
        mapping = {
            CMD_ON: (ccp.FUNC_SAUNA, True), CMD_OFF: (ccp.FUNC_SAUNA, False),
            CMD_LIGHT_ON: (ccp.FUNC_LIGHT, True), CMD_LIGHT_OFF: (ccp.FUNC_LIGHT, False),
        }
        if cmd not in mapping:
            return False
        await self.async_switch(*mapping[cmd])
        return True

    async def async_sync_time(self) -> None:
        now = dt_util.now()
        try:
            async with self._lock:
                await asyncio.wait_for(
                    self.hass.async_add_executor_job(self.client.set_time, now), timeout=8
                )
        except ccp.CommandRejected as err:
            raise HomeAssistantError("La sauna ha rifiutato l'impostazione dell'ora") from err
        except (OSError, ccp.ProtocolError, asyncio.TimeoutError) as err:
            raise HomeAssistantError(f"Impossibile impostare l'ora: {err!r}") from err
        _LOGGER.info("Effe ECC: clock set to %s", now.strftime("%Y-%m-%d %H:%M:%S"))
