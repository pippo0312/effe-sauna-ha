# v1.3.0 (2026-11-17)

Based on the analysis of the decompiled Effe ECC Android app 1.0.16
(`MECHANICS.md`, `mechanics.json`) and checked on a real sauna (Effe Sky,
ECC firmware 3.6.0623, Wi-Fi module V1.1.04-3004-06).

## New

- **Connect a sauna to Wi-Fi from Home Assistant** (first setup, or a new
  network/password): config flow option and service `effe_sauna.wifi_setup`.
  Same method as the app: EspTouch (Espressif) for 45 s, then Hi-Flying
  SmartLink for 45 s. The panel must be in configuration mode first (CHANGE
  twice, then hold on/off 5 s: REMOTE led blinking). 2.4 GHz only.
- **Search the sauna on the network** (UDP 48899, like the app): config flow
  option and service `effe_sauna.discover`.
- **Reconfigure**: change the IP of an existing entry. The entry now uses the
  controller serial as unique id, so the same sauna on a new IP is recognised.
- **Sauna pronta** (binary sensor): STATE byte 5 bit 7, the controller says the
  cabin reached the setpoint (bit documented by the app; not yet observed on a
  real heating cycle).
- **Domotica abilitata** (diagnostic binary sensor): STATE byte 24 bit 1. When
  off the controller refuses every command; HA now reports "abilita la
  domotica sul pannello" instead of failing silently.
- **Temperatura sonda sauna** (°C): the controller probe is in half degrees,
  the same scale as the setpoint (while regulating it settles on it). Shown
  only above 40 °C: when cold it reads far below room temperature.
- **Sincronizza orologio** (button) and service `effe_sauna.sync_time`
  (SET_SYS_TIME 0x39, as the app does).
- **Device info** from GET_IDENTITY (firmware, serial, product code) and
  parameters 28/30 (Wi-Fi module firmware, MAC); diagnostic sensor
  "Firmware modulo Wi-Fi".
- `tools/effe_ecc.py`: command line tool (stdlib only) with discover, state,
  info, get/on/off of every switch, colour scenes, hammam power, settime, raw
  commands and Wi-Fi provisioning.

## Changed

- Proper CCP framing (`protocol.py`): escaping, checksum check, `cmd & 0x7F`,
  ACK/NACK. Replaces the fixed-offset parser and the hard-coded command bytes
  (kept as constants for compatibility).
- Commands wait for the controller answer (up to 4 attempts, like the app)
  and one TCP request at a time (lock shared by polling and commands).

## Notes

- `Sonda Sauna (raw)` keeps its entity id and value.
- STATE byte numbers in MECHANICS.md count from the first DATA byte; earlier
  versions of this integration counted from the start of the frame (+4).
