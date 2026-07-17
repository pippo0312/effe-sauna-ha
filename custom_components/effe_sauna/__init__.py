"""Effe ECC Sauna integration."""
from __future__ import annotations

import asyncio
import logging
import socket
import time
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
SCAN_INTERVAL = timedelta(seconds=5)

# Consecutive failed polls before declaring device unavailable when the host is
# unreachable (OSError). The Effe mobile app holds an exclusive TCP connection
# while in use, causing HA polls to fail; the long grace avoids false unavail.
NO_DATA_THRESHOLD = 120  # ~600 s @ 5 s interval

# Reverse-engineered byte[9] bitfield (verified 2026-05-28 with master/light
# toggles, 10 panel toggles confirmed deterministic):
#   bit 0 (0x01) = master power ON
#   bit 1 (0x02) = light ON
#   bit 6 (0x40) = lifesign, set whenever the controller is alive
#   bits 2-5, 7  = unknown (always 0 in observed states; reserved for future
#                  reverse-engineering, e.g. heating active, error, etc.)
BIT_MASTER = 0x01
BIT_LIGHT  = 0x02

# STATUS frame marker: header f7 00 80 + opcode 0x28 (response to CMD_STATUS).
# The device sometimes prefixes the response with an unsolicited ack frame
# (e.g. after a panel button press: f7 00 80 37 ef fb a6 ...). Anchoring on
# the STATUS marker is mandatory — a fixed raw[9] read picks up garbage from
# the ack and reports a spurious "all off" state for one polling cycle.
STATUS_MARKER = b"\xf7\x00\x80\x28"
STATUS_FRAME_LEN = 41


@dataclass
class SaunaData:
    available: bool
    master_on: bool = False
    light_on: bool = False
    # byte[11]: raw sensor value from the controller's internal probe. Not a
    # linear Celsius reading: ranges roughly 14 (cold, ambient ~22°C) to 200+
    # (sauna heating). The /2 conversion used by earlier versions of this
    # integration was incorrect (NTC curve, not linear). Exposed as raw int
    # for qualitative diagnostics — use an external thermometer (Ruuvi etc.)
    # for actual cabin temperature.
    heater_raw: int | None = None
    setpoint: float | None = None      # (byte[20] & 0xFE)÷2: setpoint via knob


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
        self.no_data_streak: int = 0

    async def _async_update_data(self) -> SaunaData:
        try:
            data = await asyncio.wait_for(
                self.hass.async_add_executor_job(self._query_status),
                timeout=4,
            )
            if data.available:
                self.no_data_streak = 0
            else:
                self.no_data_streak += 1
            return data
        except asyncio.TimeoutError:
            # The inner socket work is bounded below this asyncio budget (see
            # _query_status), so this should not normally fire. If a poll still
            # overruns (e.g. the Effe app/panel is holding the socket), treat it
            # as a transient busy device — same policy as ConnectionResetError —
            # rather than raising UpdateFailed and spamming the log.
            self.no_data_streak += 1
            return self.data if self.data is not None else SaunaData(available=True)
        except Exception as err:
            self.no_data_streak += 1
            raise UpdateFailed(f"Communication error: {err}") from err

    def _query_status(self) -> SaunaData:
        try:
            # Keep the total socket budget (connect + read) strictly below the
            # 4 s asyncio.wait_for budget in _async_update_data, so a slow/busy
            # device produces a caught OSError (available=False) instead of an
            # asyncio.TimeoutError that escapes and leaks the executor thread.
            with socket.create_connection((self.host, self.port), timeout=1.5) as s:
                s.sendall(CMD_STATUS)
                raw = b""
                deadline = time.monotonic() + 1.5
                try:
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        s.settimeout(remaining)
                        chunk = s.recv(512)
                        if not chunk:
                            break
                        raw += chunk
                except socket.timeout:
                    pass

            _LOGGER.debug("status raw(%d): %s", len(raw), raw.hex())

            # Locate the STATUS frame inside the response; an unsolicited ack
            # frame may precede it (e.g. after a panel toggle).
            idx = raw.find(STATUS_MARKER)
            if idx < 0 or len(raw) < idx + STATUS_FRAME_LEN:
                # No usable STATUS frame in this response (e.g. the reply was
                # split across TCP reads) — genuinely keep the last known
                # state instead of reporting spurious all-off/unavailable.
                if self.data is not None:
                    return dataclass_replace(self.data, available=True)
                return SaunaData(available=True)
            frame = raw[idx : idx + STATUS_FRAME_LEN]

            byte9 = frame[9]
            master_on = bool(byte9 & BIT_MASTER)
            light_on  = bool(byte9 & BIT_LIGHT)
            heater_raw = frame[11]
            # byte[20] tracks the setpoint ÷2 but its LSB oscillates (firmware
            # parity bit), so mask it before dividing.
            setpoint = (frame[20] & 0xFE) / 2.0

            return SaunaData(
                available=True,
                master_on=master_on,
                light_on=light_on,
                heater_raw=heater_raw,
                setpoint=setpoint,
            )

        except ConnectionResetError:
            # Device resets connections when the Effe app holds the socket.
            # The device is reachable; state is just temporarily unreadable —
            # keep the last known state instead of reporting spurious all-off.
            if self.data is not None:
                return dataclass_replace(self.data, available=True)
            return SaunaData(available=True)
        except OSError:
            # Connection/timeout failure. Entities stay available (see
            # NO_DATA_THRESHOLD in switch.py/sensor.py, which is not driven by
            # SaunaData.available) so keep the last known state here too,
            # rather than silently reporting spurious all-off.
            if self.data is not None:
                return dataclass_replace(self.data, available=True)
            return SaunaData(available=False)

    async def async_send_command(self, cmd: bytes) -> bool:
        # Predict the resulting state and push it optimistically — the next
        # poll will confirm it from the bitfield within SCAN_INTERVAL.
        predicted = None
        if self.data is not None:
            if cmd == CMD_ON:
                predicted = dataclass_replace(self.data, master_on=True)
            elif cmd == CMD_OFF:
                # Hardware turns off the light together with the master.
                predicted = dataclass_replace(self.data, master_on=False, light_on=False)
            elif cmd == CMD_LIGHT_ON:
                predicted = dataclass_replace(self.data, light_on=True)
            elif cmd == CMD_LIGHT_OFF:
                predicted = dataclass_replace(self.data, light_on=False)

        try:
            await asyncio.wait_for(
                self.hass.async_add_executor_job(self._send_cmd, cmd),
                timeout=8,
            )
            if predicted is not None:
                self.async_set_updated_data(predicted)
            return True
        except Exception as err:
            _LOGGER.error("Command send error: %s", err)
            return False

    def _send_cmd(self, cmd: bytes) -> None:
        # The device briefly refuses new connections during transitions (e.g.
        # just after a panel button press, while the internal firmware app
        # finishes processing). Retry transparently so the user doesn't have
        # to.
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                with socket.create_connection((self.host, self.port), timeout=1.5) as s:
                    s.sendall(cmd)
                    s.settimeout(0.7)
                    try:
                        s.recv(64)  # consume ack if any
                    except (socket.timeout, ConnectionResetError):
                        pass  # RST = command processed, timeout = no ack: both are OK
                return
            except OSError as err:
                last_err = err
                time.sleep(0.35)
        if last_err is not None:
            raise last_err
