"""Effe ECC Sauna — Home Assistant integration.

Unofficial integration for Effe saunas equipped with the ECC WiFi module,
compatible with the Effe ECC Android app. Protocol reverse-engineered from
app traffic; no official API or documentation available.
"""
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

# TCP commands captured from Effe ECC Android app traffic
CMD_STATUS    = bytes.fromhex("f77d0028fba5")
CMD_ON        = bytes.fromhex("f77d0037fdfefefbaf")
CMD_OFF       = bytes.fromhex("f77d0036fdfefefbae")
CMD_LIGHT_ON  = bytes.fromhex("f77d0037fdfcfbad")
CMD_LIGHT_OFF = bytes.fromhex("f77d0036fdfcfbac")

DEFAULT_PORT = 8899
SCAN_INTERVAL = timedelta(seconds=30)


@dataclass
class SaunaData:
    available: bool
    temperature: float | None = None   # byte[9]÷2: device internal probe (32°C=standby, ~97°C=active)
    heater_temp: float | None = None   # byte[11]÷2: heating element / stones temperature
    setpoint: float | None = None      # byte[20]÷2: target temperature set via physical dial
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
        self._light_on = False                       # tracked locally (not readable from protocol)
        self._sauna_commanded_on: bool | None = None # None=unknown, True/False=last command sent

    async def _async_update_data(self) -> SaunaData:
        try:
            data = await asyncio.wait_for(
                self.hass.async_add_executor_job(self._query_status),
                timeout=6,
            )
            return data
        except Exception as err:
            raise UpdateFailed(f"Sauna communication error: {err}") from err

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

            # Byte 9: device internal probe ÷2°C
            # IMPORTANT: this probe is physically located near the heating element, NOT in the cabin.
            # It reads ambient electronics temperature (~32°C) for the first 20–30 min after power-on,
            # then jumps abruptly to ~97°C once the element heats the probe. It is NOT cabin air temp.
            temp = raw[9] / 2.0

            # Byte 11: heating element / stones temperature ÷2°C (slow variation, 96–99°C when active)
            heater_temp = raw[11] / 2.0 if len(raw) > 11 else None

            # Byte 20: target temperature set via physical dial ÷2°C (stable, typically ~99.5°C)
            setpoint = raw[20] / 2.0 if len(raw) > 20 else None

            # _light_on is managed locally — it cannot be read from the protocol response
            return SaunaData(
                available=True,
                temperature=temp,
                heater_temp=heater_temp,
                setpoint=setpoint,
                light_on=self._light_on,
            )

        except ConnectionResetError:
            # Device resets TCP connections when fully powered off — normal behaviour
            return SaunaData(available=True)
        except OSError:
            return SaunaData(available=False)

    async def async_send_command(self, cmd: bytes) -> bool:
        if cmd == CMD_ON:
            self._sauna_commanded_on = True
        elif cmd == CMD_OFF:
            self._sauna_commanded_on = False
            self._light_on = False  # hardware turns off the light together with the sauna
        elif cmd == CMD_LIGHT_ON:
            self._light_on = True
        elif cmd == CMD_LIGHT_OFF:
            self._light_on = False
        try:
            await asyncio.wait_for(
                self.hass.async_add_executor_job(self._send_cmd, cmd),
                timeout=5,
            )
            # Immediately propagate light_on state to all entities (without re-polling the device)
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
                pass  # RST = command processed, timeout = no ack: both are expected and OK
