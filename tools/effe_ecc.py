#!/usr/bin/env python3
"""Effe ECC command line tool (stdlib only, no Home Assistant needed).

Examples:
    effe_ecc.py discover [--host 192.168.1.50]
    effe_ecc.py state 192.168.1.50 [--json]
    effe_ecc.py info 192.168.1.50               identity, Wi-Fi firmware, MAC
    effe_ecc.py get 192.168.1.50 sauna_light    -> on / off
    effe_ecc.py on|off 192.168.1.50 sauna       switches: see protocol.SWITCHES
    effe_ecc.py scene 192.168.1.50 sauna 3      colour 1-9 (Logica 0-8)
    effe_ecc.py power 192.168.1.50 steam med    hammam: steam|warm min|med|max
    effe_ecc.py settime 192.168.1.50
    effe_ecc.py raw 192.168.1.50 0x50 1c        any command, data in hex
    effe_ecc.py wifi --ssid MyNet --password secret [--bssid AA:BB:..] [--method auto]

``wifi`` associates a sauna in configuration mode (CHANGE twice, then hold
on/off 5 s: REMOTE led blinking) with a 2.4 GHz network. Run it from a
computer connected to the same Wi-Fi, like the phone app does.
"""
from __future__ import annotations

import argparse
import json
import importlib.util
import pathlib
import sys
from datetime import datetime

PKG = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "effe_sauna"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, PKG / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ccp = _load("protocol")
prov = _load("provisioning")


def cmd_discover(a) -> int:
    devs = ccp.discover(timeout=a.timeout, targets=["255.255.255.255", *a.host])
    if not devs:
        print("nessuna sauna trovata (prova --host <ip>: alcuni router bloccano il broadcast)")
        return 1
    for d in devs:
        print(f"{d.host}  MAC {d.mac}  seriale {d.serial}  firmware {d.firmware}  "
              f"codice ricerca {d.product_code}  hw {d.hardware}")
    return 0


def cmd_state(a) -> int:
    st = ccp.EccClient(a.ip).get_state()
    if a.json:
        out = {name: bool(st.raw[byte] & mask)
               for name, (_t, _f, byte, mask) in ccp.SWITCHES.items()}
        out.update({
            "sauna_probe_raw": st.probe_raw, "sauna_probe_c": st.probe_c,
            "sauna_setpoint_c": st.target_c, "sauna_ready": st.ready,
            "sauna_scene": st.sauna_color, "hammam_temp": st.raw[ccp.ST_HAMMAM_TEMP],
            "steam_power": st.steam_level, "warm_power": st.warm_level,
            "hammam_scene": st.hammam_color, "domotic_enabled": st.domotic,
            "raw": st.raw.hex(),
        })
        print(json.dumps(out))
        return 0
    print(f"accesa={st.on} luce={st.light} pronta={st.ready} pannello={st.panel} "
          f"domotica={st.domotic}")
    print(f"sonda raw={st.probe_raw} (~{st.probe_c:.1f} °C, valida sopra 40 °C)  "
          f"setpoint={st.target_c:.1f} °C (raw {st.target_raw})")
    print(f"flag sauna=0x{st.sauna_flags:02X} colore={st.sauna_color} dati={st.raw.hex(' ')}")
    return 0


def cmd_info(a) -> int:
    c = ccp.EccClient(a.ip)
    ident = c.get_identity()
    print(f"firmware ECC {ident.firmware}  seriale {ident.serial}  "
          f"prodotto {ident.product_code} ({ident.product_name})")
    print(f"modulo Wi-Fi {c.get_wifi_firmware()}")
    mac = c.get_param(ccp.PARAM_MAC)
    if mac:
        print("MAC " + ":".join(f"{b:02X}" for b in mac[1:7]))
    return 0


def cmd_settime(a) -> int:
    now = datetime.now()
    ccp.EccClient(a.ip).set_time(now)
    print(f"ora impostata: {now:%Y-%m-%d %H:%M:%S}")
    return 0


def _send(ip: str, cmd: int, data: bytes) -> int:
    try:
        frame = ccp.EccClient(ip).request(cmd, data)
    except ccp.CommandRejected:
        print("rifiutato (domotica disattivata sul pannello?)")
        return 1
    print("ok" if frame.is_ack else frame.data.hex(" "))
    return 0


def cmd_get(a) -> int:
    _t, _f, byte, mask = ccp.SWITCHES[a.switch]
    print("on" if ccp.EccClient(a.ip).get_state().raw[byte] & mask else "off")
    return 0


def cmd_onoff(a) -> int:
    target, function, _b, _m = ccp.SWITCHES[a.switch]
    return _send(a.ip, ccp.CMD_ON if a.cmd == "on" else ccp.CMD_OFF, bytes((target, function)))


def cmd_scene(a) -> int:
    target = ccp.TARGET_SAUNA if a.where == "sauna" else ccp.TARGET_HAMMAM
    return _send(a.ip, ccp.CMD_RECALL_SCENE, bytes((target, a.index)))


def cmd_power(a) -> int:
    function, levels = ccp.POWER[a.what]
    value = levels[("min", "med", "max").index(a.level)]
    return _send(a.ip, ccp.CMD_SETPOINT_UPDATE, bytes((ccp.TARGET_HAMMAM, function, value)))


def cmd_raw(a) -> int:
    return _send(a.ip, int(a.command, 0), bytes.fromhex("".join(a.data)))


def cmd_wifi(a) -> int:
    print("Sul pannello: 2 volte CHANGE, poi on/off premuto 5 s (led REMOTE lampeggiante).")
    print(f"Invio di '{a.ssid}' ({a.method}), fino a {2 * a.timeout:.0f} s...")
    res = prov.provision(a.ssid, a.password, bssid=a.bssid, method=a.method,
                         local_ip=a.local_ip, timeout=a.timeout)
    if res is None:
        print("nessuna risposta dal modulo")
        return 1
    print(f"collegata con {res.method}: MAC {res.mac}, IP {res.ip}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover"); d.add_argument("--host", action="append", default=[])
    d.add_argument("--timeout", type=float, default=3.0); d.set_defaults(fn=cmd_discover)
    st = sub.add_parser("state"); st.add_argument("ip"); st.add_argument("--json", action="store_true")
    st.set_defaults(fn=cmd_state)
    for name, fn in (("info", cmd_info), ("settime", cmd_settime)):
        s = sub.add_parser(name); s.add_argument("ip"); s.set_defaults(fn=fn)
    for name, fn in (("get", cmd_get), ("on", cmd_onoff), ("off", cmd_onoff)):
        s = sub.add_parser(name); s.add_argument("ip")
        s.add_argument("switch", choices=sorted(ccp.SWITCHES)); s.set_defaults(fn=fn)
    s = sub.add_parser("scene"); s.add_argument("ip"); s.add_argument("where", choices=["sauna", "hammam"])
    s.add_argument("index", type=int, choices=range(0, 10)); s.set_defaults(fn=cmd_scene)
    s = sub.add_parser("power"); s.add_argument("ip"); s.add_argument("what", choices=sorted(ccp.POWER))
    s.add_argument("level", choices=["min", "med", "max"]); s.set_defaults(fn=cmd_power)
    s = sub.add_parser("raw"); s.add_argument("ip"); s.add_argument("command")
    s.add_argument("data", nargs="*"); s.set_defaults(fn=cmd_raw)
    w = sub.add_parser("wifi")
    w.add_argument("--ssid", required=True); w.add_argument("--password", default="")
    w.add_argument("--bssid"); w.add_argument("--local-ip")
    w.add_argument("--method", choices=["auto", "esptouch", "smartlink"], default="auto")
    w.add_argument("--timeout", type=float, default=prov.DEFAULT_TIMEOUT_S)
    w.set_defaults(fn=cmd_wifi)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
