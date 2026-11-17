"""Effe ECC local protocol (CCP over TCP 8899, discovery over UDP 48899).

Pure Python, no Home Assistant imports: used by the integration and by the
command-line tool in ``tools/effe_ecc.py``.

Sources: decompiled Effe ECC Android app 1.0.16 (see MECHANICS.md) plus the
captures made on a real sauna (Effe Sky, ECC firmware 3.6.0623).

Frame layout::

    F7  SRC  DST  CMD  DATA...  FB  CHK

* app address 0x7D, controller 0x00; replies come from 0x00 to 0x80/0x7D
* every DATA byte equal to F7, FB or FE is preceded by FE
* CHK = (SRC + DST + CMD + sum(unescaped DATA)) mod 256, never escaped
* replies carry ``CMD & 0x7F``; a one byte DATA of EF is ACK, FF is NACK
"""
from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from datetime import datetime

STX = 0xF7
ETX = 0xFB
ESC = 0xFE
APP_ADDR = 0x7D
ECC_ADDR = 0x00

ACK = 0xEF
NACK = 0xFF

CMD_SETPOINT_UPDATE = 0x10
CMD_JOB_START = 0x1E
CMD_JOB_RESULT = 0x27
CMD_GET_STATE = 0x28
CMD_FEATURES = 0x34  # unsolicited sub-frame appended to every STATE reply
CMD_OFF = 0x36
CMD_ON = 0x37
CMD_SET_SYS_TIME = 0x39
CMD_RECALL_SCENE = 0x3B
CMD_GET_PARAM = 0x50
CMD_SET_PARAM = 0x51
CMD_GET_IDENTITY = 0x72

TARGET_SAUNA = 0xFD
TARGET_HAMMAM = 0xFE
FUNC_SAUNA = 0xFE
FUNC_LIGHT = 0xFC
FUNC_CROMO = 0xFB
FUNC_MOOD = 0xEB
FUNC_IR = 0xEA
FUNC_PANEL = 0xF6

PARAM_WIFI_INFO = 28  # b"\x1c" + ASCII firmware of the Wi-Fi module
PARAM_MAC = 30        # observed: 6 byte MAC of the Wi-Fi module

TCP_PORT = 8899
UDP_PORT = 48899
DISCOVERY_PROBE = b"HF-A11ASSISTHREAD"

# GET_STATE data bytes (index into DATA, i.e. frame index - 4)
ST_HAMMAM_FLAGS = 0
ST_HAMMAM_TEMP = 1
ST_SAUNA_FLAGS = 5
ST_SAUNA_TEMP = 7
ST_STEAM_LEVEL = 14
ST_WARM_LEVEL = 15
ST_SAUNA_TARGET = 16
ST_HAMMAM_COLOR = 17
ST_SAUNA_COLOR = 18
ST_DOMOTIC = 24

# Sauna flags (DATA[5])
SF_ON = 0x01
SF_LIGHT = 0x02
SF_CROMO = 0x04
SF_BIOSAUNA = 0x08
SF_MOOD = 0x10
SF_IR = 0x20
SF_PANEL = 0x40
SF_READY = 0x80

DOMOTIC_BIT = 0x02  # DATA[24] bit 1: remote control enabled on the panel

# switch name -> (target, function, STATE data byte, bit mask)
SWITCHES = {
    "sauna": (TARGET_SAUNA, FUNC_SAUNA, ST_SAUNA_FLAGS, SF_ON),
    "sauna_light": (TARGET_SAUNA, FUNC_LIGHT, ST_SAUNA_FLAGS, SF_LIGHT),
    "sauna_cromo": (TARGET_SAUNA, FUNC_CROMO, ST_SAUNA_FLAGS, SF_CROMO),
    "sauna_mood": (TARGET_SAUNA, FUNC_MOOD, ST_SAUNA_FLAGS, SF_MOOD),
    "sauna_ir": (TARGET_SAUNA, FUNC_IR, ST_SAUNA_FLAGS, SF_IR),
    "sauna_panel": (TARGET_SAUNA, FUNC_PANEL, ST_SAUNA_FLAGS, SF_PANEL),
    "hammam_panel": (TARGET_HAMMAM, FUNC_PANEL, ST_HAMMAM_FLAGS, 0x01),
    "steam": (TARGET_HAMMAM, 0xFF, ST_HAMMAM_FLAGS, 0x02),
    "light": (TARGET_HAMMAM, FUNC_LIGHT, ST_HAMMAM_FLAGS, 0x08),
    "warm": (TARGET_HAMMAM, 0xFD, ST_HAMMAM_FLAGS, 0x10),
    "cromo": (TARGET_HAMMAM, FUNC_CROMO, ST_HAMMAM_FLAGS, 0x20),
    "mood": (TARGET_HAMMAM, FUNC_MOOD, ST_HAMMAM_FLAGS, 0x40),
}
# SETPOINT_UPDATE levels of the hammam: function -> (min, med, max)
POWER = {"steam": (0xFF, (84, 88, 92)), "warm": (0xFD, (46, 58, 70))}
COLORS = ("rosso", "giallo", "verde", "blu", "acqua", "alba", "tramonto", "mare", "bosco")

PRODUCT_NAMES = {
    0: "Touch&Steam", 1: "Aquasteam", 2: "NuvolaTouch", 3: "Sauna",
    4: "Easysteam", 5: "OmniaSteamTouch", 6: "Topcapi", 7: "LogicaTwin",
    8: "LogicaHammam", 9: "LogicaSauna", 10: "NuvolaSmartPower",
    11: "NuvolaStart", 12: "NuvolaTepidarium", 13: "Sauna IR",
    14: "Biosauna", 15: "BodyloveHammam", 16: "BodyloveSauna", 17: "Sauna",
    18: "SpaHammam", 19: "SpaSauna", 20: "SpaBiosauna", 21: "SaunaEco",
    22: "AquasteamSmart", 23: "EasysteamSmart", 24: "NuvolaInside",
    25: "Touch&SteamSmart",
}


class ProtocolError(Exception):
    """Malformed or unexpected reply."""


class CommandRejected(ProtocolError):
    """The controller answered NACK (usually: domotics disabled on the panel)."""


# --------------------------------------------------------------------------
# Framing
# --------------------------------------------------------------------------
def build_frame(cmd: int, data: bytes = b"", src: int = APP_ADDR, dst: int = ECC_ADDR) -> bytes:
    if len(data) > 505:
        raise ValueError("CCP data is limited to 505 bytes")
    out = bytearray((STX, src, dst, cmd))
    for b in data:
        if b in (STX, ETX, ESC):
            out.append(ESC)
        out.append(b)
    out.append(ETX)
    out.append((src + dst + cmd + sum(data)) & 0xFF)
    return bytes(out)


@dataclass
class Frame:
    src: int
    dst: int
    cmd: int          # already masked with 0x7F
    data: bytes
    checksum_ok: bool

    @property
    def is_ack(self) -> bool:
        return self.data == bytes((ACK,))

    @property
    def is_nack(self) -> bool:
        return self.data == bytes((NACK,))


def parse_frames(raw: bytes) -> list[Frame]:
    """Split a TCP read into CCP frames. Garbage between frames is skipped,
    a truncated frame at the end is dropped."""
    frames: list[Frame] = []
    i, n = 0, len(raw)
    while i < n:
        if raw[i] != STX:
            i += 1
            continue
        if i + 4 > n:
            break
        src, dst, cmd = raw[i + 1], raw[i + 2], raw[i + 3]
        j = i + 4
        data = bytearray()
        complete = False
        while j < n:
            b = raw[j]
            if b == ESC and j + 1 < n:
                data.append(raw[j + 1])
                j += 2
                continue
            if b == ETX:
                complete = j + 1 < n
                break
            if b == STX:  # a new frame starts: this one was truncated
                break
            data.append(b)
            j += 1
        if not complete:
            i = j if j > i else i + 1
            continue
        chk = raw[j + 1]
        ok = ((src + dst + cmd + sum(data)) & 0xFF) == chk
        frames.append(Frame(src, dst, cmd & 0x7F, bytes(data), ok))
        i = j + 2
    return frames


# --------------------------------------------------------------------------
# Decoders
# --------------------------------------------------------------------------
@dataclass
class SaunaState:
    sauna_flags: int
    hammam_flags: int
    probe_raw: int          # DATA[7]: controller probe, same scale as target
    target_raw: int         # DATA[16]: setpoint, 2 units per °C
    sauna_color: int
    hammam_color: int
    steam_level: int
    warm_level: int
    domotic: bool
    raw: bytes = field(repr=False, default=b"")

    @property
    def on(self) -> bool:
        return bool(self.sauna_flags & SF_ON)

    @property
    def light(self) -> bool:
        return bool(self.sauna_flags & SF_LIGHT)

    @property
    def ready(self) -> bool:
        return bool(self.sauna_flags & SF_READY)

    @property
    def panel(self) -> bool:
        return bool(self.sauna_flags & SF_PANEL)

    @property
    def target_c(self) -> float:
        # The LSB of DATA[16] toggles on its own: mask it (v1.2.0 finding).
        return (self.target_raw & 0xFE) / 2.0

    @property
    def probe_c(self) -> float:
        # Same scale as the setpoint: while regulating the probe settles on the
        # setpoint value (e.g. 183-191 with target 186 = 93 °C). Not accurate
        # below ~40 °C (cold readings are far below room temperature).
        return self.probe_raw / 2.0


def parse_state(data: bytes) -> SaunaState:
    if len(data) < 25:
        raise ProtocolError(f"STATE reply too short ({len(data)} bytes)")
    return SaunaState(
        sauna_flags=data[ST_SAUNA_FLAGS],
        hammam_flags=data[ST_HAMMAM_FLAGS],
        probe_raw=data[ST_SAUNA_TEMP],
        target_raw=data[ST_SAUNA_TARGET],
        sauna_color=data[ST_SAUNA_COLOR],
        hammam_color=data[ST_HAMMAM_COLOR],
        steam_level=data[ST_STEAM_LEVEL],
        warm_level=data[ST_WARM_LEVEL],
        domotic=bool(data[ST_DOMOTIC] & DOMOTIC_BIT),
        raw=bytes(data),
    )


@dataclass
class Identity:
    firmware: str
    serial: str
    product_code: int | None
    flags: int

    @property
    def product_name(self) -> str:
        if self.product_code is None:
            return "ECC"
        return PRODUCT_NAMES.get(self.product_code, f"codice {self.product_code}")


def parse_identity(data: bytes) -> Identity:
    if len(data) < 10:
        raise ProtocolError(f"IDENTITY reply too short ({len(data)} bytes)")
    major, minor = data[0], data[1]
    firmware = f"{major}.{minor}.{data[2]:02X}{data[3]:02X}"
    serial = data[4:8].hex().upper()
    if major < 3:
        code: int | None = data[8]
        flags = data[9]
    else:
        bitmap = int.from_bytes(data[8:12], "little")
        code = bitmap.bit_length() - 1 if bitmap else None
        flags = data[12] if len(data) > 12 else 0
    return Identity(firmware, serial, code, flags)


@dataclass
class DiscoveredDevice:
    host: str
    mac: str
    serial: str
    firmware: str
    vendor: int
    product_code: int
    hardware: str


def parse_discovery(text: str) -> DiscoveredDevice | None:
    """``IP,MAC,SSSSSSSSFFFFFFPPPPHH`` (see CLDevice(String))."""
    parts = text.strip().split(",")
    if len(parts) != 3 or len(parts[1]) != 12 or len(parts[2]) != 20:
        return None
    host, mac, info = parts
    try:
        socket.inet_aton(host)
        prod = int(info[14:18], 16)
    except (OSError, ValueError):
        return None
    if info.startswith(("SIWIFI", "Ch2GAT")):
        return None
    fw = info[8:14]
    return DiscoveredDevice(
        host=host,
        mac=":".join(mac[k:k + 2] for k in range(0, 12, 2)).upper(),
        serial=info[0:8].upper(),
        firmware=f"{fw[0]}.{fw[1]}.{fw[2:]}",
        vendor=(prod & 0xFC00) >> 10,
        product_code=prod & 0x3FF,
        hardware=info[18:20],
    )


def parse_wifi_info(data: bytes) -> str:
    """Parameter 28: echo of the parameter number + ASCII firmware string."""
    body = data[1:] if data and data[0] == PARAM_WIFI_INFO else data
    return body.decode("ascii", "replace").strip("\x00 ").strip()


def time_payload(now: datetime) -> bytes:
    return bytes((now.year - 2000, now.month, now.day, now.hour, now.minute, now.second))


# --------------------------------------------------------------------------
# Blocking client. One short TCP connection per request: the controller
# accepts a single client at a time and the Effe app may be holding it.
# --------------------------------------------------------------------------
class EccClient:
    def __init__(self, host: str, port: int = TCP_PORT,
                 connect_timeout: float = 1.5, read_budget: float = 1.5) -> None:
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.read_budget = read_budget

    def exchange(self, payload: bytes, until_cmd: int | None = None,
                 budget: float | None = None) -> bytes:
        """Send ``payload`` and read until the budget expires, the peer closes
        or (when ``until_cmd`` is given) a complete frame with that command
        arrived. Raises OSError on connection problems."""
        budget = self.read_budget if budget is None else budget
        raw = b""
        with socket.create_connection((self.host, self.port), timeout=self.connect_timeout) as s:
            s.sendall(payload)
            deadline = time.monotonic() + budget
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    s.settimeout(remaining)
                    chunk = s.recv(1024)
                    if not chunk:
                        break
                    raw += chunk
                    if until_cmd is not None and any(
                        f.cmd == until_cmd for f in parse_frames(raw)
                    ):
                        break
            except (socket.timeout, ConnectionResetError):
                pass
        return raw

    def request(self, cmd: int, data: bytes = b"", attempts: int = 3,
                budget: float | None = None, pause: float = 0.35) -> Frame:
        """Send a command and return the reply frame with the same command
        (like the app: up to 3 attempts)."""
        last: Exception | None = None
        for attempt in range(attempts):
            try:
                raw = self.exchange(build_frame(cmd, data), until_cmd=cmd, budget=budget)
                for f in parse_frames(raw):
                    if f.cmd == cmd:
                        if f.is_nack:
                            raise CommandRejected(f"command 0x{cmd:02X} rejected (NACK)")
                        return f
                last = ProtocolError(f"no reply to command 0x{cmd:02X} ({raw.hex()})")
            except CommandRejected:
                raise
            except OSError as err:
                last = err
            if attempt + 1 < attempts:
                time.sleep(pause)
        assert last is not None
        raise last

    # High level helpers ----------------------------------------------------
    def get_state(self) -> SaunaState:
        return parse_state(self.request(CMD_GET_STATE, attempts=1).data)

    def get_identity(self) -> Identity:
        return parse_identity(self.request(CMD_GET_IDENTITY).data)

    def get_param(self, number: int) -> bytes | None:
        """Raw parameter value, ``None`` if the controller does not have it."""
        data = self.request(CMD_GET_PARAM, bytes((number,))).data
        if data == bytes((NACK,)) or not data:
            return None
        return data

    def get_wifi_firmware(self) -> str | None:
        data = self.get_param(PARAM_WIFI_INFO)
        return parse_wifi_info(data) if data else None

    def switch(self, function: int, on: bool, target: int = TARGET_SAUNA) -> None:
        self.request(CMD_ON if on else CMD_OFF, bytes((target, function)), attempts=4)

    def set_time(self, now: datetime) -> None:
        self.request(CMD_SET_SYS_TIME, time_payload(now))


def discover(timeout: float = 2.0, targets: list[str] | None = None,
             repeats: int = 8, interval: float = 0.2) -> list[DiscoveredDevice]:
    """UDP search like the app: 8 probes 200 ms apart. ``targets`` defaults to
    the limited broadcast; unicast addresses can be added (some mesh routers
    drop broadcasts towards Wi-Fi clients)."""
    targets = targets or ["255.255.255.255"]
    found: dict[str, DiscoveredDevice] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", 0))
        s.settimeout(0.1)
        end = time.monotonic() + timeout
        sent = 0
        next_send = 0.0
        while time.monotonic() < end:
            now = time.monotonic()
            if sent < repeats and now >= next_send:
                for t in targets:
                    try:
                        s.sendto(DISCOVERY_PROBE, (t, UDP_PORT))
                    except OSError:
                        pass
                sent += 1
                next_send = now + interval
            try:
                pkt, _addr = s.recvfrom(256)
            except socket.timeout:
                continue
            dev = parse_discovery(pkt.decode("ascii", "replace"))
            if dev and dev.vendor == 1:
                found[dev.mac] = dev
    return list(found.values())
