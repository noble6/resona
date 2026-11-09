"""Offline unit tests (no PipeWire needed): presets, shm contract, parsers, IR reader.

    python3 tests/test_units.py [--net]     (--net also checks the live AutoEq database)
"""
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from resona import __version__, correction, hardware, presets, shm, updater  # noqa: E402

fails = 0


def check(ok, msg):
    global fails
    print(("  ok   " if ok else "  FAIL ") + msg)
    fails += not ok


# shm param order must match the C enum exactly
hdr = (ROOT / "engine" / "resona_shm.h").read_text()
body = hdr[hdr.index("enum {"):hdr.index("P_COUNT")]
c_names = [n.lower()[2:] for n in re.findall(r"\bP_[A-Z0-9_]+", body)]
check(c_names == shm.PARAMS, f"Python PARAMS mirror the C enum ({len(c_names)} params)")
check(f"RESONA_VERSION {shm.VERSION}u" in hdr, "shm version matches")

# every preset key is a real engine parameter
keys = set(presets.DEFAULTS)
check(keys == set(shm.PARAMS), "DEFAULTS covers exactly the engine parameters")
bad = [(n, k) for n, (_, _, p) in presets.PROFILES.items() for k in p if k != "eq" and k not in keys]
check(not bad, f"profiles only use known params {bad}")
for dev in presets.DEVICE_MODES:
    for name in presets.PROFILES:
        out = presets.profile_params(name, dev)
        assert set(out) <= keys, (name, dev, set(out) - keys)
        assert not (out.get("hrtf_on") and out.get("xfeed_on")), (name, dev)
check(True, "profile × device overlays are valid and never enable HRTF + crossfeed together")

for dev in presets.DEVICE_MODES:
    for previous in presets.PROFILES:
        for name in presets.PROFILES:
            actual = dict(presets.DEFAULTS)
            actual.update(presets.profile_params(previous, dev))
            actual.update(presets.profile_params(name, dev))
            expected = dict(presets.DEFAULTS)
            expected.update(presets.profile_params(name, dev))
            assert actual == expected, (previous, name, dev)
check(True, "profile transitions do not retain effects from the previous profile")

# EqualizerAPO / AutoEq parsing
pre, f = correction.parse_parametric("""Preamp: -6.7 dB
Filter 1: ON LSC Fc 105 Hz Gain 1.9 dB Q 0.70
Filter 2: ON PK Fc 160 Hz Gain -5.8 dB Q 0.41
Filter 3: OFF PK Fc 999 Hz Gain 9 dB Q 1
Filter 4: ON HSC Fc 10 kHz Gain -0.3 dB Q 0.70
Filter: ON LS 12dB Fc 80 Hz Gain 3 dB
Filter 6: ON HP Fc 20 Hz""")
check(pre == -6.7 and [x["type"] for x in f] == ["LSC", "PK", "HSC", "LSC", "HP"] and f[2]["freq"] == 10000,
      f"EqualizerAPO parser: preamp {pre}, {len(f)} filters, OFF skipped, kHz handled")
r = correction.response_db([{"type": "PK", "freq": 1000, "gain": 6, "q": 1}], np.array([1000.0]))
check(abs(r[0] - 6) < 0.01, f"response math matches RBJ peak (+{r[0]:.2f} dB)")

# ViPER DDC (sign convention from JamesDSP vdc.c: a1/a2 stored negated)
vdc = "SR_44100:1.0,2.0,1.0,0.5,-0.25\nSR_48000:0.9,0.1,0.0,0.4,-0.2,1,0,0,0,0"
v = correction.parse_vdc(vdc, 48000)
check(len(v) == 2 and v[0]["a1"] == -0.4 and v[0]["a2"] == 0.2, "DDC parser picks the 48 kHz set and flips a1/a2")
v = correction.parse_vdc(vdc, 96000)
check(v[0]["b0"] == 0.9, "DDC for 96 kHz falls back to the closest (48 kHz) set")
check(correction.safe_preamp([{"type": "PK", "freq": 100, "gain": 8, "q": 1}]) == -8.0, "safe preamp prevents clipping")

# IR reader: 24-bit stereo PCM
tmp = Path(tempfile.mkdtemp())
x = np.zeros((1000, 2)); x[0] = [0.5, 0.25]
pcm = (x * 8388607).astype("<i4")
raw = b"".join(int(s).to_bytes(4, "little", signed=True)[:3] for s in pcm.reshape(-1))
hdrb = b"RIFF" + (36 + len(raw)).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little") + \
       (1).to_bytes(2, "little") + (2).to_bytes(2, "little") + (44100).to_bytes(4, "little") + \
       (44100 * 6).to_bytes(4, "little") + (6).to_bytes(2, "little") + (24).to_bytes(2, "little")
(tmp / "ir.wav").write_bytes(hdrb + b"data" + len(raw).to_bytes(4, "little") + raw)
info = correction.read_ir(str(tmp / "ir.wav"))
check(info["channels"] == 2 and info["frames"] == 1000 and abs(info["gain"] - 2.0) < 0.01,
      f"IR reader: 24-bit stereo, normalising gain {info['gain']}")

# layouts
check(hardware.layout_of("front-left,front-right")["bits"] == 0, "stereo layout")
l71 = hardware.layout_of("front-left,front-right,front-center,lfe,rear-left,rear-right,side-left,side-right")
check(l71["name"] == "7.1" and l71["bits"] == 15, "7.1 layout → centre, LFE, side + rear")
check(hardware.profile_kind("output:iec958-ac3-surround-51") == "encoded" and
      hardware.profile_kind("output:iec958-stereo") == "optical" and
      hardware.profile_kind("output:hdmi-surround71") == "hdmi", "profile classification (AC3, optical, HDMI)")

# bass voicings: names match the engine table, every profile picks a valid one
src = (ROOT / "engine" / "resona_dsp.c").read_text()
check(src.count("BASS_BALANCED, BASS_SUB, BASS_PUNCHY, BASS_WARM") == 1 and len(presets.BASS_TYPES) == 4,
      "bass types mirror the engine voicings")
check(all(0 <= p[2].get("bass_type", 0) < 4 for p in presets.PROFILES.values()), "profiles use valid bass types")

# shared memory is safe to touch after close (late UI writes during shutdown used to segfault)
with tempfile.TemporaryDirectory() as d:
    st = shm.SharedState(str(Path(d) / "shm"))
    st.write({"bass_type": 2})
    st.close()
    st.write({"bass_amt": 1}); st.write_corr([{"type": "PK", "freq": 100, "gain": 3, "q": 1}])
    a_, b_ = st.latest(256)
    check(st.heartbeat == 0 and st.meters()["out_l"] == 0 and len(a_) == 256 and len(st.ieq_gains()) == 10,
          "shared memory access after close is a safe no-op")

# updater
check(updater.version_tuple("v2.10.0") > updater.version_tuple("2.9.9") > updater.version_tuple("2.9"),
      "release versions compare numerically")
check(updater.install_kind() == "source", "a git checkout is never overwritten by the updater")
check(updater.FREQ_DAYS == {"manual": 0, "weekly": 7, "monthly": 30}, "update schedules")

if "--net" in sys.argv:
    idx = correction.autoeq_index(max_age_days=0)
    hits = correction.autoeq_search(idx, "hd 650")
    check(len(idx) > 5000 and hits and "650" in hits[0]["name"], f"AutoEq index: {len(idx)} headphones, '{hits[0]['name']}'")
    pre, f = correction.parse_parametric(correction.autoeq_fetch(hits[0]))
    check(len(f) >= 5 and pre < 0, f"AutoEq fetch+parse: {len(f)} filters, preamp {pre} dB")
    import urllib.request
    real = urllib.request.urlopen("https://raw.githubusercontent.com/Audio4Linux/JDSP4Linux/master/resources/assets/vdc/mh750.vdc", timeout=20).read().decode()
    v = correction.parse_vdc(real, 48000)
    ok = all(abs(b["a2"]) < 1 for b in v)
    check(len(v) > 3 and ok, f"real JamesDSP DDC file: {len(v)} stable biquads")
    rel = updater.check()
    check(rel["tag"].startswith("v") and rel["tarball"].startswith("https://api.github.com/repos/noble6/resona/"),
          f"latest GitHub release found: {rel['tag']} (running {__version__})")

print("ALL PASSED" if not fails else f"FAILED ({fails})")
sys.exit(1 if fails else 0)
