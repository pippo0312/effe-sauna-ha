"""Tests of the HA-free modules (run: python3 -m pytest tests/ or python3 tests/test_protocol.py)."""
import importlib.util
import pathlib
import sys
from datetime import datetime

BASE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "effe_sauna"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ccp = _load("protocol")
prov = _load("provisioning")

# Captured on the real sauna (Effe Sky), 2026-11-17, sauna off, light off.
STATE_REPLY = bytes.fromhex(
    "f7008028000000000040000600000800000054" "28ba010101000000000200" "6f0004020300140" "05afb17"
    "f700803401ffffff00fffbb1"
)
IDENTITY_REPLY = bytes.fromhex("f700807203060623012345670000010000fbf5")  # serial anonymised
PARAM28_REPLY = bytes.fromhex("f70080501c56312e312e30342d333030342d3036fbeb")
PARAM_NACK = bytes.fromhex("f7008050fffbcf")


def test_build_frame_matches_app_and_captures():
    assert ccp.build_frame(ccp.CMD_GET_STATE).hex() == "f77d0028fba5"
    # MECHANICS.md example: FE in the data is escaped, checksum is not.
    assert ccp.build_frame(ccp.CMD_ON, bytes((0xFD, 0xFE))).hex() == "f77d0037fdfefefbaf"
    assert ccp.build_frame(ccp.CMD_OFF, bytes((0xFD, 0xFE))).hex() == "f77d0036fdfefefbae"
    assert ccp.build_frame(ccp.CMD_ON, bytes((0xFD, 0xFC))).hex() == "f77d0037fdfcfbad"
    assert ccp.build_frame(ccp.CMD_OFF, bytes((0xFD, 0xFC))).hex() == "f77d0036fdfcfbac"


def test_escape_roundtrip():
    data = bytes((0xF7, 0x01, 0xFB, 0xFE, 0x00))
    f = ccp.parse_frames(ccp.build_frame(0x51, data, src=0x00, dst=0x80))
    assert len(f) == 1 and f[0].data == data and f[0].checksum_ok


def test_parse_state_reply():
    frames = ccp.parse_frames(STATE_REPLY)
    assert [f.cmd for f in frames] == [0x28, 0x34]
    assert all(f.checksum_ok for f in frames)
    st = ccp.parse_state(frames[0].data)
    assert len(frames[0].data) == 35
    assert st.sauna_flags == 0x40 and not st.on and not st.light and st.panel and not st.ready
    assert st.probe_raw == 6
    assert st.target_raw == 0xBA and st.target_c == 93.0
    assert st.domotic is True
    assert st.steam_level == 84 and st.sauna_color == 1


def test_bitfield_matches_v12_frame_indices():
    # v1.2.x read frame[9] / frame[11] / frame[20]: DATA index = frame index - 4.
    data = ccp.parse_frames(STATE_REPLY)[0].data
    assert data[5] == STATE_REPLY[9] and data[7] == STATE_REPLY[11] and data[16] == STATE_REPLY[20]
    for flags, on, light in ((0x40, 0, 0), (0x41, 1, 0), (0x42, 0, 1), (0x43, 1, 1)):
        d = bytearray(data); d[5] = flags
        st = ccp.parse_state(bytes(d))
        assert (st.on, st.light) == (bool(on), bool(light))


def test_ack_prefix_and_split_reply():
    ack = bytes.fromhex("f7008037effba6")
    frames = ccp.parse_frames(ack + STATE_REPLY)
    assert frames[0].is_ack and frames[0].cmd == 0x37 and frames[1].cmd == 0x28
    # truncated STATE frame: dropped, no exception
    assert [f.cmd for f in ccp.parse_frames(STATE_REPLY[:20])] == []
    assert ccp.parse_frames(bytes.fromhex("f7008037fffbb6"))[0].is_nack


def test_identity():
    ident = ccp.parse_identity(ccp.parse_frames(IDENTITY_REPLY)[0].data)
    assert ident.firmware == "3.6.0623"
    assert ident.serial == "01234567"
    assert ident.product_code == 16 and ident.product_name == "BodyloveSauna"


def test_param28_and_nack():
    f = ccp.parse_frames(PARAM28_REPLY)[0]
    assert f.checksum_ok and ccp.parse_wifi_info(f.data) == "V1.1.04-3004-06"
    assert ccp.parse_frames(PARAM_NACK)[0].is_nack


def test_discovery_reply():
    dev = ccp.parse_discovery("192.168.1.50,98F4AB001122,01234567360623040000")
    assert dev.host == "192.168.1.50" and dev.mac == "98:F4:AB:00:11:22"
    assert dev.serial == "01234567" and dev.firmware == "3.6.0623" and dev.vendor == 1
    assert ccp.parse_discovery("garbage") is None
    assert ccp.parse_discovery("192.168.0.9,AABBCCDDEEFF,SIWIFI00000000000000") is None


def test_time_payload():
    assert ccp.time_payload(datetime(2026, 11, 17, 9, 5, 7)) == bytes((26, 11, 17, 9, 5, 7))


def test_crc8_maxim():
    assert prov.crc8(b"123456789") == 0xA1
    assert prov.crc8(b"") == 0


def test_esptouch_layout():
    ssid, pwd = b"casa", b"secret12"
    bssid, ip = bytes.fromhex("aabbccddeeff"), bytes((192, 168, 0, 118))
    lens = prov.esptouch_data_lengths(ssid, pwd, bssid, ip)
    n_codes = 5 + len(ip) + len(pwd) + len(ssid) + len(bssid)
    assert len(lens) == 3 * n_codes
    total_len = 5 + 4 + len(pwd) + len(ssid)
    seqs = [lens[3 * k + 1] - 40 - 0x100 for k in range(n_codes)]
    # head 0..4, bssid bytes interleaved every 4 codes from position 5
    assert seqs[:6] == [0, 1, 2, 3, 4, total_len]
    assert sorted(seqs) == list(range(total_len + 6))
    # each code: high byte of first/last u16 is 0, crc nibbles check
    for k in range(n_codes):
        a, b, c = (x - 40 for x in lens[3 * k: 3 * k + 3])
        assert a >> 8 == 0 and c >> 8 == 0 and b >> 8 == 1
        u8 = ((a & 0x0F) << 4) | (c & 0x0F)
        crc = ((a >> 4) << 4) | (c >> 4)
        assert crc == prov.crc8([u8, b & 0xFF])
    # first code carries total_len, xor code is consistent
    u = lambda k: (((lens[3 * k] - 40) & 0x0F) << 4) | ((lens[3 * k + 2] - 40) & 0x0F)
    x = 0
    for v in [total_len, len(pwd), prov.crc8(ssid), prov.crc8(bssid), *ip, *pwd, *ssid]:
        x ^= v
    assert u(0) == total_len and u(4) == x


def test_smartlink_message():
    msg = prov.smartlink_message("casa", "secret12")
    assert msg[:4] == bytes((4, 8, 32, 0)) and msg[4:8] == b"casa" and len(msg) % 2 == 0
    assert prov.parse_bssid("aa:bb:cc:dd:ee:ff") == bytes.fromhex("aabbccddeeff")
    assert prov.parse_bssid(None) == bytes(6)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
