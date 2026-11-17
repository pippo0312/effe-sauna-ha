# Effe ECC Sauna — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Unofficial Home Assistant custom component for controlling **Effe** saunas equipped with the ECC WiFi module, compatible with the [Effe ECC Android app](https://play.google.com/store/apps/details?id=com.effegibi.effeecc).

Developed and tested on an **[Effe Sky](https://www.effe.it/prodotto/sky/)** sauna. Should work on other Effe models using the same ECC WiFi controller and app.

---

## ⚠️ Disclaimer

- **Unofficial / unsupported.** The local protocol was worked out from the traffic of the Effe ECC app, from the app itself and from tests on a real sauna. Effe provides no official API or documentation.
- **No warranty.** Use at your own risk. The author provides no guarantee of correctness, reliability, or compatibility with future firmware versions.
- Personal project shared as-is to help other Effe owners. Issues and pull requests welcome, but response time is not guaranteed.

---

## What's new in v1.3.0

- **Connect the sauna to Wi-Fi from Home Assistant**: first setup, or a new network or password. Same method as the app (EspTouch, then SmartLink). See [Wi-Fi setup](#wi-fi-setup).
- **Search the sauna on the network** (UDP 48899, like the app), and **reconfigure** to change the IP of an existing entry. The entry now uses the controller serial as unique id, so the same sauna on a new IP is recognised.
- New entities: **Sauna pronta** (ready), **Domotica abilitata** (remote control enabled on the panel), **Temperatura sonda sauna** (°C), **Sincronizza orologio** button, **Firmware modulo Wi-Fi** (diagnostic).
- Device page shows ECC firmware, serial, product code, Wi-Fi module firmware and MAC.
- Commands that the controller refuses (domotics disabled on the panel) now raise a clear error instead of failing silently.
- Proper CCP framing (escaping, checksum, ACK/NACK) in `protocol.py`; one TCP request at a time.
- `tools/effe_ecc.py`: command line tool, Python standard library only.

Full list in [CHANGELOG.md](CHANGELOG.md). Upgrading from v1.2.x needs no change: existing entity ids are kept.

---

## Features

### Entities

| Entity | Type | Description |
|--------|------|-------------|
| **Sauna** | Switch | Master power ON / OFF. Reflects the real device state (panel + HA + app). |
| **Luce Sauna** | Switch | Cabin light. Independent of master power. |
| **Sauna pronta** | Binary sensor | The controller reports that the cabin reached the setpoint (state byte 5, bit 7). |
| **Temperatura sonda sauna** | Sensor (°C) | The controller's own probe, in °C. Shown only above 40 °C, see [Temperature sensors](#temperature-sensors). |
| **Temperatura Impostata Sauna** | Sensor (°C) | Setpoint. |
| **Sonda Sauna (raw)** | Sensor | Raw byte of the probe (half degrees). |
| **Domotica abilitata** | Binary sensor (diagnostic) | Remote control enabled on the panel. When off, the controller refuses every command. |
| **Firmware modulo Wi-Fi** | Sensor (diagnostic) | Wi-Fi module firmware; attributes: ECC firmware, serial, product code, MAC. |
| **Sincronizza orologio** | Button | Sets the Home Assistant time on the controller, as the app does. |

### Services

| Service | What it does |
|---------|--------------|
| `effe_sauna.discover` | Searches Effe ECC modules on the network and returns IP, MAC, serial, firmware. Optional `hosts` to query directly if your router drops broadcasts. |
| `effe_sauna.wifi_setup` | Sends network and password to a module in configuration mode. Returns the MAC and the new IP; an existing entry for the same sauna follows the new IP. |
| `effe_sauna.sync_time` | Same as the button, for every configured sauna. |

### Not implemented

The protocol also has commands for chromotherapy, mood light, infrared, steam and warm power (hammam). They are available in `tools/effe_ecc.py`, but they are not entities because the tested sauna does not have them. If you own such a model and can test them, please open an issue.

---

## Wi-Fi setup

Works for the first setup and to move the sauna to another network or password.

1. Put the module in configuration mode. Sauna: press **CHANGE** twice, then hold **on/off** for 5 s until the **REMOTE** led blinks. Hammam / Logica: hold on/off for 5 s until the House icon blinks.
2. In Home Assistant: **Settings → Devices & Services → Add Integration → Effe ECC Sauna → Connect a sauna to Wi-Fi**, or call the service `effe_sauna.wifi_setup`.
3. Enter the **2.4 GHz** network name and password. The BSSID (MAC of the access point nearest to the sauna) is optional.

Home Assistant then sends the data for 45 s with **EspTouch** and, if nothing answers, 45 s more with **SmartLink**. The module answers with its MAC and its new IP.

Notes:

- The data travel as UDP multicast from Home Assistant to the router, which has to pass them on over Wi-Fi. Some mesh systems filter multicast towards wireless clients; if Home Assistant (often on a cable) gets no answer, run the same procedure from a computer on the Wi-Fi: `python3 tools/effe_ecc.py wifi --ssid MyNet --password secret`.
- The module only supports 2.4 GHz networks. There is no command to choose the Wi-Fi channel: the module uses the router's channel.
- The module's own access point (`effegibi-XXXXXXXX`) is not used by this procedure.

---

## Temperature sensors

| Sensor | Source | Behaviour |
|--------|--------|-----------|
| **Temperatura sonda sauna** | state byte 7 / 2 | The probe the controller regulates on, in the same half-degree scale as the setpoint: while heating it settles on the setpoint (raw 183-191 with setpoint 186 = 93 °C). It sits near the ceiling, so it reads higher than the cabin air at bench height. Below about 40 °C it reads far too low (raw 5 with the cabin at 21 °C), so the sensor is unknown below 40 °C. |
| **Sonda Sauna (raw)** | state byte 7 | The same value, unscaled. |
| **Temperatura Impostata Sauna** | `(state byte 16 & 0xFE) / 2` | Setpoint; the lowest bit toggles on its own and is masked. |

For the cabin air temperature use an external sensor ([Ruuvi Tag](https://ruuvi.com/) or any Bluetooth thermometer supported by Home Assistant).

---

## Protocol notes

The ECC controller sits behind an Espressif Wi-Fi module that passes bytes between TCP and the controller's serial line.

| | |
|---|---|
| Discovery | UDP **48899**, send `HF-A11ASSISTHREAD`; reply `IP,MAC,<20 chars>` (serial, firmware, product, hardware) |
| Control | TCP **8899**, no authentication, **one client at a time** |
| Frame | `F7 SRC DST CMD DATA… FB CHK`; app = `0x7D`, controller = `0x00` |
| Escape | every DATA byte equal to `F7`, `FB` or `FE` is preceded by `FE` |
| Checksum | `(SRC + DST + CMD + sum of unescaped DATA) mod 256`, not escaped |
| Replies | `CMD & 0x7F`; DATA `EF` = ACK, `FF` = NACK (refused) |

### Commands

| CMD | Name | DATA |
|-----|------|------|
| `0x28` | GET_STATE | — |
| `0x72` | GET_IDENTITY | — (reply: firmware, serial, product bitmap) |
| `0x37` / `0x36` | ON / OFF | target, function: sauna `FD FE`, light `FD FC`, chromo `FD FB`, mood `FD EB`, IR `FD EA`; hammam target `FE` |
| `0x3B` | RECALL_SCENE | target, colour 1-9 |
| `0x10` | SETPOINT_UPDATE | hammam power: `FE FF 84/88/92` (steam), `FE FD 46/58/70` (warm) |
| `0x39` | SET_SYS_TIME | year-2000, month, day, hour, minute, second |
| `0x50` | GET_PARAM | parameter number (28 = Wi-Fi module firmware, 30 = MAC) |

### GET_STATE reply (DATA bytes)

| Byte | Meaning |
|------|---------|
| 0 | hammam flags |
| 5 | sauna flags: bit 0 on, 1 light, 2 chromo, 3 biosauna, 4 mood, 5 IR, 6 panel, 7 ready |
| 7 | sauna probe (half degrees) |
| 16 | sauna setpoint (half degrees, LSB masked) |
| 17 / 18 | hammam / sauna colour |
| 24 | bit 1 = domotics (remote control) enabled |

Byte numbers count from the first DATA byte. Versions up to 1.2.x counted from the start of the frame (+4: byte 9, 11, 20).

The reply to GET_STATE is followed by an unsolicited `0x34` frame (`01 ff ff ff 00 ff` on the tested sauna); after a panel action an ACK frame can come first.

### Connection behaviour

- The controller accepts only **one TCP connection at a time**. While the Effe app is connected, Home Assistant polls fail; the integration keeps the last known state for up to 10 minutes.
- Right after a state change the device may refuse connections or reset them; requests are retried.

---

## Command line tool

`tools/effe_ecc.py` needs only Python 3 (no Home Assistant):

```
effe_ecc.py discover [--host 192.168.1.50]
effe_ecc.py state 192.168.1.50 [--json]
effe_ecc.py info 192.168.1.50
effe_ecc.py on|off 192.168.1.50 sauna|sauna_light|…
effe_ecc.py scene 192.168.1.50 sauna 3
effe_ecc.py power 192.168.1.50 steam med
effe_ecc.py settime 192.168.1.50
effe_ecc.py raw 192.168.1.50 0x50 1c
effe_ecc.py wifi --ssid MyNet --password secret
```

Tests of the protocol code: `python3 tests/test_protocol.py`.

---

## Requirements

- Effe sauna with ECC WiFi module
- Compatible with the [Effe ECC Android app](https://play.google.com/store/apps/details?id=com.effegibi.effeecc)
- Device reachable on your local network, domotics (remote control) enabled on the panel
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

**Settings → Devices & Services → Add Integration → Effe ECC Sauna**, then:

- **Search the sauna on the network**: lists the saunas that answer the UDP search;
- **Enter the IP address**: IP and port (default 8899);
- **Connect a sauna to Wi-Fi**: see [Wi-Fi setup](#wi-fi-setup).

To change the IP later: **Effe ECC Sauna → ⋮ → Reconfigure**. Assigning a static IP (DHCP reservation) to the module is still recommended.

---

## Tested hardware

- **Effe Sky** sauna — 3-phase, ~7.6 kW, ECC firmware 3.6.0623 (product code 16), Wi-Fi module firmware V1.1.04-3004-06.

---

## Debugging

```yaml
logger:
  default: info
  logs:
    custom_components.effe_sauna: debug
```

You will see the raw STATUS hex of every poll, useful for reporting protocol differences from other models.

---

## Contributing

- Found this working on another Effe model? Open an issue with the output of `tools/effe_ecc.py info <ip>` and `state <ip> --json`.
- Tested chromotherapy, mood, IR or hammam commands? Pull requests very welcome.
- Found a bug? Open an issue with your HA version and the relevant log lines.
