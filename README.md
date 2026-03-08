# Effe ECC Sauna — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Unofficial Home Assistant custom component for controlling **Effe** saunas equipped with the ECC WiFi module, compatible with the [Effe ECC Android app](https://play.google.com/store/apps/details?id=com.effegibi.effeecc).

Developed and tested on an **[Effe Sky](https://www.effe.it/prodotto/sky/)** sauna. Should work on other Effe models using the same ECC WiFi controller and app.

---

## ⚠️ Disclaimer

- **Unofficial / unsupported.** This integration is based on a fully reverse-engineered TCP binary protocol. Effe provides no official API or documentation.
- **No warranty.** Use at your own risk. The author provides no guarantee of correctness, reliability, or compatibility with future firmware versions.
- **Temperature sensors are unreliable.** The device does not expose accurate cabin air temperature (see [Temperature sensors](#temperature-sensors) below).
- This is a personal project shared as-is to help other Effe owners. Issues and pull requests are welcome, but response time is not guaranteed.

---

## Features

### Entities exposed

| Entity | Type | Description |
|--------|------|-------------|
| **Sauna** | Switch | Power ON / OFF |
| **Sauna Light** | Switch | Internal light, controllable independently at any temperature |
| **Probe Temperature** | Sensor | Device internal probe — see note below |
| **Heater Temperature** | Sensor | Heating element / stones probe |
| **Setpoint** | Sensor | Target temperature set via physical dial |

### Not implemented / not tested

The Effe ECC app supports additional features that are **not present on the tested Effe Sky model** and have therefore not been reverse-engineered or implemented:

- Mood lighting
- Chromotherapy (colour therapy)
- RGB light control
- Multiple heating zones

If you own a model with these features and want to contribute protocol bytes, please open an issue.

---

## Temperature sensors

> **Important:** none of the temperature sensors in this integration measure actual cabin air temperature. For real cabin temperature, use an external sensor placed inside the sauna (e.g. a [Ruuvi Tag](https://ruuvi.com/) or any Bluetooth thermometer supported by Home Assistant).

| Sensor | Source | Behaviour |
|--------|--------|-----------|
| **Probe Temperature** | byte[9] ÷ 2 | Reads ambient electronics (~32°C) for the first 20–30 min after power-on, then jumps abruptly to ~97°C once the heating element physically heats the probe. Useful to detect operating state (threshold ~40°C). |
| **Heater Temperature** | byte[11] ÷ 2 | Slow-varying, typically 96–99°C when active. Relative indicator only. |
| **Setpoint** | byte[20] ÷ 2 | Reflects the physical dial position. Stable and reliable, but not independently calibrated (typically ~99.5°C at maximum). |

All values have 0.5°C resolution (the device encodes temperature as `raw_byte / 2`).

---

## Protocol notes

The device communicates over **TCP port 8899** using a proprietary binary protocol (Espressif/ESP32 chipset). The protocol was reverse-engineered by capturing traffic between the Effe ECC Android app and the device. There is no official documentation.

Key findings:
- STATUS query returns **53 bytes** (41 main + 12 fixed secondary)
- **ON/OFF state is not directly readable** from the protocol response — it is inferred from probe temperature (>40°C = on) and from the last command sent
- **Light state is not readable** — tracked locally and reset on HA restart
- The device always responds, even in standby (with probe reading ~32°C)
- TCP connections are reset by the device after each command — this is normal

Known commands (hex):

| Command | Hex |
|---------|-----|
| STATUS  | `f77d0028fba5` |
| ON      | `f77d0037fdfefefbaf` |
| OFF     | `f77d0036fdfefefbae` |
| LIGHT ON  | `f77d0037fdfcfbad` |
| LIGHT OFF | `f77d0036fdfcfbac` |

---

## Requirements

- Effe sauna with ECC WiFi module
- Compatible with the [Effe ECC Android app](https://play.google.com/store/apps/details?id=com.effegibi.effeecc)
- Device must be reachable on your local network (same subnet as Home Assistant, or properly routed)
- Default TCP port: **8899**

---

## Installation

### Via HACS (recommended)

1. In HACS → **Integrations** → **⋮** → **Custom repositories**
2. Add `https://github.com/pippo0312/effe-sauna-ha` as category **Integration**
3. Install **Effe ECC Sauna** from HACS
4. Restart Home Assistant

### Manual

1. Download or clone this repository
2. Copy `custom_components/effe_sauna/` into your HA `config/custom_components/` directory
3. Restart Home Assistant

---

## Configuration

1. **Settings → Devices & Services → Add Integration**
2. Search for **Effe ECC Sauna**
3. Enter the device **IP address** (find it in your router's DHCP table or the Effe ECC app) and **port** (default: 8899)

The integration tests connectivity before saving. Assign a static IP to the device in your router for reliable operation.

To reload the integration without a full HA restart:
**Settings → Devices & Services → Effe ECC Sauna → ⋮ → Reload**

---

## Known limitations

- **Light state is optimistic**: not readable from the device — state is tracked locally and lost on HA restart or integration reload
- **ON/OFF state** is inferred, not explicitly provided by the protocol
- **Poll interval**: 30 seconds
- Temperature sensors measure device-internal probes, not cabin air temperature

---

## Tested hardware

- **Effe Sky** sauna — 3-phase, ~7.6 kW (3 × ~2.5 kW elements), ECC WiFi module, firmware version unknown

---

## Contributing

- Found this working on another Effe model? Please open an issue describing the model and any differences observed.
- Reverse-engineered the mood/chromo/RGB protocol bytes? Pull requests are very welcome.
- Found a bug? Open an issue with your HA version and the relevant log lines (enable debug logging: `custom_components.effe_sauna: debug`).
