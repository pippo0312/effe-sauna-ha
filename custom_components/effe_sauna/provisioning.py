"""Wi-Fi provisioning of the Effe ECC Wi-Fi module (first association or a
change of network/password).

The app does it in two passes (SmartConfigViewModel):

A. EspTouch v0.3.7 (Espressif): only the *length* of UDP datagrams sent to
   234.n.n.n:7001 matters. Guide code 515/514/513/512 for 2 s, then the data
   code for 4 s, repeated, 8 ms between packets, 45 s overall. The module
   answers on UDP 18266 with ``[len(ssid)+len(pwd)+9, MAC(6), IP(4)]``.
B. Hi-Flying SmartLink v7 (fallback, 45 s): multicast to 239.48.0.0 and
   239.46.b1.b2 on port 6000, reply on UDP 49999.

The module must be in configuration mode first. On a sauna: press CHANGE
twice, then hold on/off for 5 s, until the REMOTE led blinks. Only 2.4 GHz
networks are supported.

Pure Python (stdlib only): used by the integration and by tools/effe_ecc.py.
"""
from __future__ import annotations

import hashlib
import socket
import threading
import time
from dataclasses import dataclass

ESPTOUCH_PORT = 7001
ESPTOUCH_REPLY_PORT = 18266
SMARTLINK_PORT = 6000
SMARTLINK_REPLY_PORT = 49999

GUIDE_CODE = (515, 514, 513, 512)
EXTRA_LEN = 40
EXTRA_HEAD_LEN = 5

GUIDE_MS = 2000
DATA_MS = 4000
PACKET_INTERVAL_S = 0.008
DEFAULT_TIMEOUT_S = 45.0


@dataclass
class ProvisionResult:
    method: str
    mac: str
    ip: str


# --------------------------------------------------------------------------
# EspTouch encoding (port of com.espressif.iot.esptouch 0.3.7.x)
# --------------------------------------------------------------------------
def _crc8_table() -> list[int]:
    table = []
    for dividend in range(256):
        rem = dividend
        for _ in range(8):
            rem = (rem >> 1) ^ 0x8C if rem & 1 else rem >> 1
        table.append(rem)
    return table


_CRC8 = _crc8_table()


def crc8(data: bytes | list[int]) -> int:
    """CRC-8/MAXIM (poly 0x8C reflected, init 0), as the CRC8 class of the app."""
    value = 0
    for b in data:
        value = _CRC8[(b ^ value) & 0xFF]
    return value


def _data_code(u8: int, index: int) -> list[int]:
    """One DataCode -> three datagram lengths."""
    crc = crc8([u8 & 0xFF, index & 0xFF])
    data_hi, data_lo = (u8 >> 4) & 0x0F, u8 & 0x0F
    crc_hi, crc_lo = (crc >> 4) & 0x0F, crc & 0x0F
    b = [0x00, (crc_hi << 4) | data_hi, 0x01, index & 0xFF, 0x00, (crc_lo << 4) | data_lo]
    return [((b[k] << 8) | b[k + 1]) + EXTRA_LEN for k in range(0, 6, 2)]


def esptouch_data_lengths(ssid: bytes, password: bytes, bssid: bytes,
                          ip: bytes, ssid_hidden: bool = True) -> list[int]:
    """DatumCode of EspTouch 0.3.7: list of datagram lengths (3 per code).

    ``ssid_hidden`` = True sends the SSID itself too (the app does: EsptouchTask
    init with hidden = 1), so the module does not need to see the beacon.
    """
    if len(bssid) != 6 or len(ip) != 4:
        raise ValueError("bssid must be 6 bytes and ip 4 bytes")
    total_len = (EXTRA_HEAD_LEN + len(ip) + len(password) + len(ssid)) & 0xFF
    pwd_len = len(password) & 0xFF
    ssid_crc = crc8(ssid)
    bssid_crc = crc8(bssid)

    codes: list[tuple[int, int]] = [(total_len, 0), (pwd_len, 1), (ssid_crc, 2), (bssid_crc, 3)]
    total_xor = total_len ^ pwd_len ^ ssid_crc ^ bssid_crc
    for i, c in enumerate(ip):
        total_xor ^= c
        codes.append((c, i + EXTRA_HEAD_LEN))
    for i, c in enumerate(password):
        total_xor ^= c
        codes.append((c, i + EXTRA_HEAD_LEN + len(ip)))
    for i, c in enumerate(ssid):
        total_xor ^= c
        if ssid_hidden:
            codes.append((c, i + EXTRA_HEAD_LEN + len(ip) + len(password)))
    codes.insert(4, (total_xor, 4))
    insert_at = EXTRA_HEAD_LEN
    for i, c in enumerate(bssid):
        code = (c, total_len + i)
        if insert_at >= len(codes):
            codes.append(code)
        else:
            codes.insert(insert_at, code)
        insert_at += 4

    lengths: list[int] = []
    for u8, index in codes:
        lengths.extend(_data_code(u8, index))
    return lengths


def parse_bssid(text: str | None) -> bytes:
    if not text:
        return bytes(6)
    clean = text.replace(":", "").replace("-", "").strip()
    if len(clean) != 12:
        raise ValueError(f"invalid BSSID: {text!r}")
    return bytes.fromhex(clean)


def local_ip_towards(host: str = "8.8.8.8") -> str:
    """IP of the interface used to reach ``host`` (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, 9))
        return s.getsockname()[0]


class _Multicast:
    def __init__(self, local_ip: str) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        try:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                                 socket.inet_aton(local_ip))
        except OSError:
            pass
        self.count = 0
        self._pad = b"1" * 1600

    def send_len(self, length: int, addr: tuple[str, int]) -> None:
        try:
            self.sock.sendto(self._pad[:length], addr)
        except OSError:
            pass

    def next_esptouch_host(self, broadcast: bool) -> str:
        if broadcast:
            return "255.255.255.255"
        n = 1 + self.count % 100
        self.count += 1
        return f"234.{n + 1}.{n}.{n}"

    def close(self) -> None:
        self.sock.close()


def _listen(port: int) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", port))
    s.settimeout(0.05)
    return s


def run_esptouch(ssid: str, password: str, bssid: str | None = None,
                 local_ip: str | None = None, timeout: float = DEFAULT_TIMEOUT_S,
                 broadcast: bool = False,
                 stop: threading.Event | None = None) -> ProvisionResult | None:
    ssid_b, pwd_b = ssid.encode("utf-8"), password.encode("utf-8")
    local_ip = local_ip or local_ip_towards()
    lengths = esptouch_data_lengths(ssid_b, pwd_b, parse_bssid(bssid),
                                    socket.inet_aton(local_ip))
    expect_first = (len(ssid_b) + len(pwd_b) + 9) & 0xFF

    tx = _Multicast(local_ip)
    rx = _listen(ESPTOUCH_REPLY_PORT)
    try:
        start = time.monotonic()
        idx = 0
        phase_start = start
        in_guide = True
        while time.monotonic() - start < timeout:
            if stop is not None and stop.is_set():
                return None
            now = time.monotonic()
            if in_guide:
                for g in GUIDE_CODE:
                    tx.send_len(g, (tx.next_esptouch_host(broadcast), ESPTOUCH_PORT))
                    time.sleep(PACKET_INTERVAL_S)
                if (now - phase_start) * 1000 >= GUIDE_MS:
                    in_guide, phase_start = False, now
            else:
                for k in range(3):
                    tx.send_len(lengths[(idx + k) % len(lengths)],
                                (tx.next_esptouch_host(broadcast), ESPTOUCH_PORT))
                    time.sleep(PACKET_INTERVAL_S)
                idx = (idx + 3) % len(lengths)
                if (now - phase_start) * 1000 >= DATA_MS:
                    in_guide, phase_start = True, now
            try:
                pkt, _ = rx.recvfrom(64)
            except socket.timeout:
                continue
            if len(pkt) >= 11 and pkt[0] == expect_first:
                mac = ":".join(f"{b:02X}" for b in pkt[1:7])
                ip = socket.inet_ntoa(pkt[7:11])
                return ProvisionResult("esptouch", mac, ip)
        return None
    finally:
        tx.close()
        rx.close()


# --------------------------------------------------------------------------
# Hi-Flying SmartLink v7 (multicast variant), fallback of the app
# --------------------------------------------------------------------------
def smartlink_message(ssid: str, password: str) -> bytes:
    ssid_b, pwd_b = ssid.encode("utf-8"), password.encode("utf-8")
    pmk = hashlib.pbkdf2_hmac("sha1", pwd_b, ssid_b, 4096, 32) if pwd_b else b""
    msg = bytes((len(ssid_b), len(pwd_b), len(pmk), 0)) + ssid_b + pwd_b + pmk
    if len(msg) % 2:
        msg += b"\x00"
    return msg


def run_smartlink(ssid: str, password: str, local_ip: str | None = None,
                  timeout: float = DEFAULT_TIMEOUT_S,
                  stop: threading.Event | None = None) -> ProvisionResult | None:
    local_ip = local_ip or local_ip_towards()
    msg = smartlink_message(ssid, password)
    tx = _Multicast(local_ip)
    rx = _listen(SMARTLINK_REPLY_PORT)
    try:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            for _ in range(5):
                tx.send_len(30, ("239.48.0.0", SMARTLINK_PORT))
                time.sleep(PACKET_INTERVAL_S)
            for i in range(0, len(msg), 2):
                if stop is not None and stop.is_set():
                    return None
                tx.send_len(30 + i // 2, (f"239.46.{msg[i]}.{msg[i + 1]}", SMARTLINK_PORT))
                time.sleep(PACKET_INTERVAL_S)
            try:
                pkt, addr = rx.recvfrom(256)
            except socket.timeout:
                continue
            text = pkt.decode("ascii", "replace")
            if text.startswith("smart_config"):
                mac = text[len("smart_config"):].strip(" :\x00")
                return ProvisionResult("smartlink", mac.upper(), addr[0])
        return None
    finally:
        tx.close()
        rx.close()


def provision(ssid: str, password: str, bssid: str | None = None,
              method: str = "auto", local_ip: str | None = None,
              timeout: float = DEFAULT_TIMEOUT_S,
              stop: threading.Event | None = None) -> ProvisionResult | None:
    """Same order as the app: EspTouch, then SmartLink if nothing answered."""
    if method in ("auto", "esptouch"):
        res = run_esptouch(ssid, password, bssid, local_ip, timeout, stop=stop)
        if res or method == "esptouch":
            return res
    if method in ("auto", "smartlink"):
        return run_smartlink(ssid, password, local_ip, timeout, stop=stop)
    raise ValueError(f"unknown method {method!r}")


__all__ = [
    "ProvisionResult", "crc8", "esptouch_data_lengths", "smartlink_message",
    "run_esptouch", "run_smartlink", "provision", "parse_bssid", "local_ip_towards",
]
