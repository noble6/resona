"""Hardware detection: sound cards, codecs, connectors, profiles (stereo / surround /
HDMI / S/PDIF optical / AC3), sample-rate & bit-depth capabilities, Bluetooth codecs,
and Hi-Res mode (PipeWire clock rates + resampler quality)."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

CFG = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "pipewire"
HIRES_CONF = CFG / "pipewire.conf.d" / "90-resona-hires.conf"
RESAMPLE_CONFS = [CFG / "pipewire-pulse.conf.d" / "90-resona-resample.conf",
                  CFG / "client.conf.d" / "90-resona-resample.conf"]
STANDARD_RATES = [44100, 48000, 88200, 96000, 176400, 192000, 352800, 384000]

POS = {"front-left": "FL", "front-right": "FR", "front-center": "FC", "lfe": "LFE",
       "rear-left": "RL", "rear-right": "RR", "side-left": "SL", "side-right": "SR", "mono": "MONO"}


def _run(*args: str, timeout: float = 4.0) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _json(*args: str):
    try:
        return json.loads(_run(*args) or "[]")
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------- channel layouts
def layout_of(channel_map: str) -> dict:
    """pactl channel_map → PipeWire positions + engine layout bits (1 C, 2 LFE, 4 side, 8 rear)."""
    pos = [POS.get(c.strip(), "") for c in (channel_map or "").split(",") if c.strip()]
    if not pos or "" in pos or "MONO" in pos:
        return {"positions": ["FL", "FR"], "channels": 2, "bits": 0, "name": "Stereo"}
    bits = (1 if "FC" in pos else 0) | (2 if "LFE" in pos else 0) | \
           (4 if "SL" in pos else 0) | (8 if "RL" in pos else 0)
    n = len(pos)
    names = {2: "Stereo", 3: "2.1" if "LFE" in pos else "3.0", 4: "4.0" if "LFE" not in pos else "3.1",
             5: "4.1" if "LFE" in pos else "5.0", 6: "5.1", 8: "7.1"}
    return {"positions": pos, "channels": n, "bits": bits, "name": names.get(n, f"{n} ch")}


# ---------------------------------------------------------------- profiles
def profile_kind(name: str) -> str:
    n = name.lower()
    if n == "off":
        return "off"
    if "pro-audio" in n:
        return "pro"
    if "ac3" in n or "dts" in n:
        return "encoded"         # Dolby Digital / DTS live encode over optical
    if "iec958" in n:
        return "optical"
    if "hdmi" in n:
        return "hdmi"
    if "a2dp" in n or "headset" in n or "hfp" in n or "hsp" in n:
        return "bluetooth"
    if "surround" in n:
        return "surround"
    return "stereo"


def _codec_name(card_index: str) -> str:
    try:
        for f in sorted(Path(f"/proc/asound/card{card_index}").glob("codec#*")):
            m = re.search(r"^Codec:\s*(.+)$", f.read_text(errors="ignore"), re.M)
            if m:
                return m.group(1).strip()
    except OSError:
        pass
    return ""


def _dac_bits(card_index: str) -> int:
    """Real converter depth from the HDA codec (PipeWire only reports the 32-bit container)."""
    best = 0
    try:
        for f in Path(f"/proc/asound/card{card_index}").glob("codec#*"):
            for blk in f.read_text(errors="ignore").split("Node 0x")[1:]:
                if "Output" not in blk.split("\n")[0]:
                    continue
                for m in re.finditer(r"bits \[0x[0-9a-f]+\]:\s*([\d ]+)", blk):
                    best = max([best] + [int(b) for b in m.group(1).split()])
    except OSError:
        pass
    return best


def displays(card_index: str) -> list[dict]:
    """Connected HDMI/DP sinks (TV, monitor, AV receiver) and the audio formats they accept."""
    out = []
    for f in sorted(Path(f"/proc/asound/card{card_index}").glob("eld#*")):
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        if not re.search(r"monitor_present\s+1", txt):
            continue
        name = (re.search(r"monitor_name\s+(.*)", txt) or [None, "Display"])[1].strip()
        fmts = []
        for i in range(16):
            ct = re.search(rf"sad{i}_coding_type\s+\[0x[0-9a-f]+\]\s+(\S+)", txt)
            if not ct:
                break
            ch = re.search(rf"sad{i}_channels\s+(\d+)", txt)
            rates = re.search(rf"sad{i}_rates\s+\[0x[0-9a-f]+\]\s+([\d ]+)", txt)
            bits = re.search(rf"sad{i}_bits\s+\[0x[0-9a-f]+\]\s+([\d ]+)", txt)
            r = [int(x) for x in rates.group(1).split()] if rates else []
            b = [int(x) for x in bits.group(1).split()] if bits else []
            fmts.append({"coding": ct.group(1), "channels": int(ch.group(1)) if ch else 2,
                         "maxRate": max(r) if r else 0, "bits": max(b) if b else 0})
        out.append({"name": name, "formats": fmts})
    return out


def _usb_rates(card_index: str) -> list[int]:
    rates = set()
    for f in Path(f"/proc/asound/card{card_index}").glob("stream*"):
        try:
            txt = f.read_text(errors="ignore")
        except OSError:
            continue
        play = txt.split("Capture:")[0]
        for m in re.finditer(r"Rates:\s*([\d, ]+)", play):
            rates.update(int(r) for r in m.group(1).replace(" ", "").split(",") if r)
    return sorted(rates)


def _node_caps() -> dict:
    """node.name -> {rates, formats, bits, now_rate, now_format} from pw-dump EnumFormat."""
    caps = {}
    for o in _json("pw-dump"):
        info = o.get("info") or {}
        props = info.get("props") or {}
        if props.get("media.class") != "Audio/Sink":
            continue
        rates, fmts = set(), set()
        for f in (info.get("params") or {}).get("EnumFormat", []):
            r = f.get("rate")
            if isinstance(r, dict):
                lo, hi = r.get("min", r.get("default")), r.get("max", r.get("default"))
                if lo and hi:
                    rates.update(x for x in STANDARD_RATES + [32000] if lo <= x <= hi)
                elif r.get("default"):
                    rates.add(r["default"])
                rates.update(v for k, v in r.items() if k.startswith("alt") and isinstance(v, int))
            elif isinstance(r, int):
                rates.add(r)
            fm = f.get("format")
            if isinstance(fm, dict):
                fmts.update(v for v in fm.values() if isinstance(v, str))
            elif isinstance(fm, str):
                fmts.add(fm)
        now = ((info.get("params") or {}).get("Format") or [{}])[0]
        bits = 0
        for f in fmts:
            m = re.search(r"(\d+)", f)
            if m:
                b = int(m.group(1))
                bits = max(bits, 24 if b == 32 and f.startswith("S24_32") else b)
        caps[props.get("node.name", "")] = {
            "rates": sorted(rates), "formats": sorted(fmts), "bits": bits,
            "now_rate": now.get("rate"), "now_format": now.get("format"),
            "codec": props.get("api.bluez5.codec") or "",
        }
    return caps


def scan() -> list[dict]:
    """Everything the Hardware page shows, one entry per card (with its sinks)."""
    cards = _json("pactl", "-f", "json", "list", "cards")
    sinks = _json("pactl", "-f", "json", "list", "sinks")
    caps = _node_caps()
    out = []
    for c in cards:
        p = c.get("properties", {})
        idx = p.get("alsa.card", "")
        bus = p.get("device.bus", "") or ("bluetooth" if c["name"].startswith("bluez") else "")
        codec = p.get("alsa.mixer_name") or _codec_name(idx) if idx else ""
        card_sinks = []
        for s in sinks:
            sp = s.get("properties", {})
            same = (idx and sp.get("alsa.card") == idx) or sp.get("device.name") == c["name"]
            if not same or s["name"].startswith("resona"):
                continue
            cap = caps.get(s["name"], {})
            rates = cap.get("rates") or (_usb_rates(idx) if bus == "usb" else [])
            bits = (_dac_bits(idx) if idx else 0) or cap.get("bits", 0)
            if "hdmi" in s["name"] and idx:
                lpcm = [f for d in displays(idx) for f in d["formats"] if f["coding"] == "LPCM"]
                if lpcm:
                    bits = max(f["bits"] for f in lpcm) or bits
            lay = layout_of(s.get("channel_map", ""))
            card_sinks.append({
                "name": s["name"], "description": s.get("description", s["name"]),
                "channels": lay["channels"], "layout": lay["name"],
                "rates": rates, "maxRate": max(rates) if rates else 0, "bits": bits,
                "nowRate": cap.get("now_rate") or 0, "nowFormat": cap.get("now_format") or "",
                "hires": bool(rates and max(rates) >= 88200 and bits >= 24),
                "btCodec": cap.get("codec", ""),
                "state": s.get("state", ""),
            })
        profiles = []
        for name, v in c.get("profiles", {}).items():
            if name == "off" or name.startswith("input:"):
                continue
            profiles.append({"name": name, "description": v.get("description", name),
                             "available": bool(v.get("available", True)), "kind": profile_kind(name)})
        ports = [{"name": n, "description": v.get("description", n), "type": v.get("type", ""),
                  "available": v.get("availability", "") != "not available",
                  "plugged": v.get("availability", "") == "available"}
                 for n, v in c.get("ports", {}).items() if v.get("direction", "output") != "input"
                 and not any(k in (v.get("type") or "").lower() for k in ("mic", "line in"))
                 and "input" not in n]
        out.append({
            "name": c["name"],
            "title": p.get("device.product.name") or p.get("device.description") or c["name"],
            "vendor": p.get("device.vendor.name", ""),
            "codec": codec, "driver": p.get("alsa.driver_name", "") or p.get("device.api", ""),
            "bus": bus, "formFactor": p.get("device.form_factor", ""),
            "activeProfile": c.get("active_profile", ""),
            "profiles": profiles, "ports": ports, "sinks": card_sinks,
            "bluetooth": c["name"].startswith("bluez"),
            "displays": displays(idx) if idx else [],
        })
    return out


def set_profile(card: str, profile: str) -> bool:
    return subprocess.run(["pactl", "set-card-profile", card, profile], capture_output=True).returncode == 0


# ---------------------------------------------------------------- Bluetooth codecs
def bt_codecs(card: str) -> list[str]:
    out = _run("pactl", "send-message", f"/card/{card}/bluez", "list-codecs")
    try:
        return [c.get("name", "") for c in json.loads(out) if c.get("name")]
    except (json.JSONDecodeError, AttributeError):
        return []


def bt_switch_codec(card: str, codec: str) -> bool:
    return subprocess.run(["pactl", "send-message", f"/card/{card}/bluez", "switch-codec", json.dumps(codec)],
                          capture_output=True).returncode == 0


# ---------------------------------------------------------------- Hi-Res mode
def clock_settings() -> dict:
    txt = _run("pw-metadata", "-n", "settings", "0")
    out = {}
    for m in re.finditer(r"key:'clock\.([\w.-]+)' value:'([^']*)'", txt):
        out[m.group(1)] = m.group(2)
    return out


def hires_rates(max_rate: int) -> list[int]:
    return [r for r in STANDARD_RATES if r <= max(max_rate, 48000)]


def hires_enabled() -> bool:
    return HIRES_CONF.exists()


def set_hires(on: bool, max_rate: int = 192000) -> list[int]:
    """Let PipeWire follow each stream's native rate (44.1 / 88.2 / 96 / 192 kHz …) instead
    of resampling everything to 48 kHz. Applied live and persisted for next login."""
    if on:
        rates = hires_rates(max_rate)
        HIRES_CONF.parent.mkdir(parents=True, exist_ok=True)
        HIRES_CONF.write_text("# written by Resona (Hi-Res mode)\ncontext.properties = {\n"
                              f"    default.clock.allowed-rates = [ {' '.join(map(str, rates))} ]\n}}\n")
        _run("pw-metadata", "-n", "settings", "0", "clock.allowed-rates", f"[ {' '.join(map(str, rates))} ]")
        return rates
    if HIRES_CONF.exists():
        HIRES_CONF.unlink()
    _run("pw-metadata", "-n", "settings", "-d", "0", "clock.allowed-rates")
    return []


def hq_resampler_enabled() -> bool:
    return RESAMPLE_CONFS[0].exists()


def set_hq_resampler(on: bool) -> None:
    """Highest-quality SRC for every app stream (takes effect for streams opened after an audio restart)."""
    for f in RESAMPLE_CONFS:
        if on:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("# written by Resona\nstream.properties = {\n    resample.quality = 14\n}\n")
        elif f.exists():
            f.unlink()


def restart_audio() -> None:
    subprocess.Popen(["systemctl", "--user", "restart", "wireplumber", "pipewire", "pipewire-pulse"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
