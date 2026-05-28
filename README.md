# Effe ECC Sauna — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Unofficial Home Assistant custom component for controlling **Effe** saunas equipped with the ECC WiFi module, compatible with the [Effe ECC Android app](https://play.google.com/store/apps/details?id=com.effegibi.effeecc).

Developed and tested on an **[Effe Sky](https://www.effe.it/prodotto/sky/)** sauna. Should work on other Effe models using the same ECC WiFi controller and app.

---

## ⚠️ Disclaimer

- **Unofficial / unsupported.** This integration is based on a fully reverse-engineered TCP binary protocol. Effe provides no official API or documentation.
- **No warranty.** Use at your own risk. The author provides no guarantee of correctness, reliability, or compatibility with future firmware versions.
- **Sauna cabin temperature is NOT exposed by the device.** The only temperature-related value (`Sonda Sauna raw`) is a raw NTC sensor reading, not Celsius. Use an external thermometer (Ruuvi Tag, Bluetooth, etc.) for real cabin temperature.
- Personal project shared as-is to help other Effe owners. Issues and pull requests welcome, but response time is not guaranteed.

---

## What's new in v1.2.0

Major rewrite based on **complete reverse-engineering of the status byte 9 bitfield** (May 2026). Previous releases incorrectly interpreted byte 9 as a Celsius temperature; it is in fact a packed status bitfield.

### Bugs fixed since v1.1.1

- **Turning on the light from the panel no longer triggers a false "sauna on" state in Home Assistant.** Previous versions read `byte[9] / 2` as temperature: `0x40` (light off) → 32.0°C → master "off", `0x42` (light on) → 33.0°C → master "on". The bitfield-aware decoder fixes this.
- **Light state from panel toggles is now reflected in HA within one polling cycle (≤5 s)**, not just commands sent from HA. Previous versions tracked light only locally.
- **Master power state is read directly from the device**, no longer inferred from probe temperature.
- **Spurious "everything off" reading after panel toggles eliminated.** Frames are now parsed by searching for the STATUS marker (`f7 00 80 28`) rather than a fixed offset — the device sometimes prefixes the response with an ack frame that shifted the bit interpretation.
- **Failed commands retried transparently.** The device briefly refuses TCP connections during firmware transitions; the integration retries up to 4× with short backoff.
- **Setpoint sensor is now stable.** Previous versions oscillated between e.g. 91.0 °C and 91.5 °C because the firmware toggles the LSB of byte 20 as a parity bit — now masked.

### Other changes

- Poll interval reduced from 10 s → **5 s** (more responsive UI).
- Removed `Probe Temperature` entity (was meaningless — value was the byte 9 bitfield divided by 2).
- Renamed heater temperature sensor to `Sonda Sauna (raw)` with **no unit and no device class**. The raw NTC value is not a linear Celsius reading and earlier releases were misleading.
- Removed dead code: `RestoreEntity`, custom `_handle_coordinator_update` overrides, `_light_on` local tracking, `_sauna_commanded_on`.
- Optimistic state push: HA updates the UI immediately on user command, polling confirms within 5 s.

### Breaking changes (migration from v1.1.x)

- Entity `sensor.effe_ecc_sauna_temperatura_sauna` is **removed**. Delete any dashboard cards or automations referencing it.
- Entity `sensor.effe_ecc_sauna_temperatura_resistenza_sauna` is **replaced** by `sensor.effe_ecc_sauna_sonda_sauna_raw`. The new entity has no unit (raw byte value, not Celsius). Update dashboard cards.

---

## Features

### Entities exposed

| Entity | Type | Description |
|--------|------|-------------|
| **Sauna** | Switch | Master power ON / OFF. Reflects real device state (panel + HA + app). |
| **Luce Sauna** | Switch | Internal light. Independent of master power. Reflects real device state. |
| **Temperatura Impostata Sauna** | Sensor (°C) | Setpoint dial position. |
| **Sonda Sauna (raw)** | Sensor (no unit) | Raw NTC value from the controller's internal probe. Not Celsius. See [Temperature sensors](#temperature-sensors). |

### Not implemented (not present on the tested Effe Sky model)

- Mood lighting
- Chromotherapy (colour therapy)
- RGB light control
- Multiple heating zones
- Audio (if equipped)

If you own a model with these features and want to contribute protocol bytes (capture with `tcpdump`/Wireshark while toggling from the Android app), please open an issue.

---

## Protocol notes

The device communicates over **TCP port 8899** with a proprietary binary protocol (Espressif/ESP32 chipset). The protocol was reverse-engineered by:
- Capturing the local TCP traffic between the Effe ECC Android app and the device.
- Probing the controller directly with handcrafted frames while observing state changes from the physical panel.

There is no official documentation.

### CMD_STATUS response — byte map

The device responds to `CMD_STATUS` with a **41-byte frame** (sometimes prefixed by an unsolicited 7-byte ack frame after a state change). The frame is anchored by the marker `f7 00 80 28`.

| Byte | Meaning |
|------|---------|
| 0–3  | Frame header + opcode echo (`f7 00 80 28`) |
| **9** | **Status bitfield** (see below) |
| 11   | Raw NTC sensor value (exposed as `Sonda Sauna raw`) |
| 20   | Setpoint × 2 (LSB is parity, mask with `0xFE`) |
| 40   | Frame checksum |
| —    | Other bytes constant in observed states (unknown meaning) |

### Byte 9 bitfield (the key finding)

| Bit | Mask | Meaning |
|-----|------|---------|
| 0   | `0x01` | Master power ON |
| 1   | `0x02` | Light ON |
| 6   | `0x40` | Lifesign (always 1 when controller responding) |
| 2–5, 7 | — | Unknown (always 0 in all observed states) |

Examples:
- `0x40` → all off (master off, light off, controller alive)
- `0x41` → master on, light off
- `0x42` → master off, light on
- `0x43` → master on, light on

Verified with 10 physical panel toggles, 100% deterministic.

### Known commands

| Command | Hex | Notes |
|---------|-----|-------|
| STATUS    | `f7 7d 00 28 fb a5` | Query state |
| ON        | `f7 7d 00 37 fd fe fe fb af` | Master on |
| OFF       | `f7 7d 00 36 fd fe fe fb ae` | Master off |
| LIGHT ON  | `f7 7d 00 37 fd fc fb ad` | Light on |
| LIGHT OFF | `f7 7d 00 36 fd fc fb ac` | Light off |

Checksum rule (last byte): `opcode + body_constant`. For STATUS: `0x28 + 0x7d = 0xa5`. For master commands: `opcode + 0x78`. For light commands: `opcode + 0x76`.

### Connection behaviour

- The device accepts only **one TCP connection at a time**. While the Effe Android app is connected, polling from HA will fail with `OSError` until the app disconnects.
- When the master power is off, the device sometimes **resets new connections** (RST) before completing the handshake — but it still serves status correctly once master is on.
- The device may briefly refuse connections immediately after a state change (panel toggle); the integration retries automatically.

---

## Temperature sensors

> The Effe controller does **not** expose actual cabin air temperature on this protocol. The only varying sensor (byte 11) is a raw NTC value, not a linear Celsius reading. For real cabin temperature, place an external sensor inside the sauna ([Ruuvi Tag](https://ruuvi.com/) or any Bluetooth thermometer supported by Home Assistant).

| Sensor | Source | Behaviour |
|--------|--------|-----------|
| **Sonda Sauna (raw)** | `byte[11]` | Raw NTC value 0–255 (no unit). Roughly: 14 = cold idle, ~92 = warming, 200+ = hot. Non-linear with actual temperature. Useful as a qualitative indicator that the heating element is active. |
| **Temperatura Impostata Sauna** | `(byte[20] & 0xFE) / 2.0` | Stable, accurate. Reflects the physical dial position. |

---

## Requirements

- Effe sauna with ECC WiFi module
- Compatible with the [Effe ECC Android app](https://play.google.com/store/apps/details?id=com.effegibi.effeecc)
- Device reachable on your local network (same subnet as Home Assistant, or properly routed)
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

## Tested hardware

- **Effe Sky** sauna — 3-phase, ~7.6 kW (3 × ~2.5 kW elements), ECC Module 2.0 ESP WiFi controller, firmware version reported by the device unknown.

---

## Debugging

Enable debug logging in `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.effe_sauna: debug
```

You will see the raw STATUS hex of every poll, useful for reporting protocol differences from other models.

---

## Contributing

- Found this working on another Effe model? Open an issue describing the model and any byte differences observed.
- Reverse-engineered the mood/chromo/RGB/audio protocol bytes? Pull requests very welcome.
- Found a bug? Open an issue with your HA version and the relevant log lines.

---

## Acknowledgements

The v1.2.0 protocol rewrite is the result of a focused reverse-engineering session combining:
- Active probing of the controller with crafted frames
- Cross-correlation of byte differences with physical state changes (panel toggles)
- Pcap captures of the device's spontaneous broadcast / multicast traffic (none found — the device only speaks unicast on TCP 8899)
