"""Effe ECC Sauna integration."""
from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass, replace as dataclass_replace
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

_LOGGER = logging.getLogger(__name__)

DOMAIN = "effe_sauna"
PLATFORMS = [Platform.SWITCH, Platform.SENSOR]

# TCP commands (captured from real app traffic)
CMD_STATUS    = bytes.fromhex("f77d0028fba5")
CMD_ON        = bytes.fromhex("f77d0037fdfefefbaf")
CMD_OFF       = bytes.fromhex("f77d0036fdfefefbae")
CMD_LIGHT_ON  = bytes.fromhex("f77d0037fdfcfbad")
CMD_LIGHT_OFF = bytes.fromhex("f77d0036fdfcfbac")

DEFAULT_PORT = 8899
SCAN_INTERVAL = timedelta(seconds=30)

# Number of consecutive failed polls before reporting the sauna as off/unavailable.
# The Effe app holds an exclusive TCP connection while in use, causing HA polls to fail
# with OSError (ConnectionRefused). A streak threshold avoids false OFF states during
# brief app interactions.
NO_DATA_THRESHOLD = 20  # ~600 seconds (device drops TCP for 3+ min after Effe app commands)


@dataclass
class SaunaData:
    available: bool
    temperature: float | None = None   # byte[9]÷2: internal probe (32°C=standby, 97°C=active)
    heater_temp: float | None = None   # byte[11]÷2: heater/stones temperature
    setpoint: float | None = None      # byte[20]÷2: setpoint set via knob
    heating: bool = False
    light_on: bool = False


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = SaunaCoordinator(hass, entry.data[CONF_HOST], entry.data[CONF_PORT])
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


class SaunaCoordinator(DataUpdateCoordinator[SaunaData]):
    def __init__(self, hass: HomeAssistant, host: str, port: int) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=SCAN_INTERVAL)
        self.host = host
        self.port = port
        self._light_on = False  # tracked locally (not readable from status packet)
        self._sauna_commanded_on: bool | None = None  # None=unknown, True/False=last sent command
        self.no_data_streak: int = 0  # consecutive polls with no usable temperature data

    async def _async_update_data(self) -> SaunaData:
        try:
            data = await asyncio.wait_for(
                self.hass.async_add_executor_job(self._query_status),
                timeout=6,
            )
            if data.available and data.temperature is not None:
                self.no_data_streak = 0
            else:
                self.no_data_streak += 1
            return data
        except Exception as err:
            self.no_data_streak += 1
            raise UpdateFailed(f"Communication error: {err}") from err

    def _query_status(self) -> SaunaData:
        try:
            with socket.create_connection((self.host, self.port), timeout=4) as s:
                s.sendall(CMD_STATUS)
                s.settimeout(2)
                raw = b""
                try:
                    while True:
                        chunk = s.recv(512)
                        if not chunk:
                            break
                        raw += chunk
                except socket.timeout:
                    pass

            _LOGGER.debug("status raw(%d): %s", len(raw), raw.hex())

            if len(raw) < 41:
                return SaunaData(available=True)

            # Byte 9: internal probe ÷2 (32°C=standby, ~97°C=active)
            temp = raw[9] / 2.0
            # Byte 11: heater/stones temperature ÷2, rises slowly 96-99°C
            heater_temp = raw[11] / 2.0 if len(raw) > 11 else None
            # Byte 20: setpoint set via knob ÷2 (stable, ~99.5°C)
            setpoint = raw[20] / 2.0 if len(raw) > 20 else None

            # _light_on: tracked locally (not readable from status packet)

            return SaunaData(
                available=True,
                temperature=temp,
                heater_temp=heater_temp,
                setpoint=setpoint,
                light_on=self._light_on,
            )

        except ConnectionResetError:
            # Device resets connections when OFF
            return SaunaData(available=True)
        except OSError:
            return SaunaData(available=False)

    async def async_send_command(self, cmd: bytes) -> bool:
        if cmd == CMD_ON:
            self._sauna_commanded_on = True
        elif cmd == CMD_OFF:
            self._sauna_commanded_on = False
            self._light_on = False   # hardware turns off the light together with the sauna
        elif cmd == CMD_LIGHT_ON:
            self._light_on = True
        elif cmd == CMD_LIGHT_OFF:
            self._light_on = False
        try:
            await asyncio.wait_for(
                self.hass.async_add_executor_job(self._send_cmd, cmd),
                timeout=5,
            )
            # Push light_on state to all entities immediately (without re-polling the device)
            if self.data is not None:
                self.async_set_updated_data(
                    dataclass_replace(self.data, light_on=self._light_on)
                )
            return True
        except Exception as err:
            _LOGGER.error("Command send error: %s", err)
            return False

    def _send_cmd(self, cmd: bytes) -> None:
        with socket.create_connection((self.host, self.port), timeout=4) as s:
            s.sendall(cmd)
            s.settimeout(1)
            try:
                s.recv(64)  # consume ack if any
            except (socket.timeout, ConnectionResetError):
                pass  # RST = command processed, timeout = no ack: both are OK
