"""Live test: apps that open the hardware device directly (FMOD/Wwise games such as
War Thunder) get routed back through Resona; apps sent to another device are left alone.
Silent: uses null sinks.

    python3 tests/test_capture_live.py
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="resona-cfg-")
os.environ["RESONA_SINK_NAME"] = "resona_cap_sink"
os.environ["RESONA_SHM"] = tempfile.mktemp(prefix="resona-shm-")
os.environ["RESONA_TEST_TARGET"] = "resona_cap_hw"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import numpy as np  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from resona.backend import Backend  # noqa: E402

fails = 0


def check(ok, msg):
    global fails
    print(("  ok   " if ok else "  FAIL ") + msg)
    fails += not ok


def pump(secs):
    loop = QEventLoop()
    QTimer.singleShot(int(secs * 1000), loop.quit)
    loop.exec()


def wait_for(cond, secs=8.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        pump(0.1)
        if cond():
            return True
    return False


def null_sink(name):
    return subprocess.run(["pactl", "load-module", "module-null-sink", f"sink_name={name}"],
                          capture_output=True, text=True).stdout.strip()


def sink_of(app):
    sinks = {s["index"]: s["name"] for s in json.loads(subprocess.run(
        ["pactl", "-f", "json", "list", "sinks"], capture_output=True, text=True).stdout)}
    for si in json.loads(subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"],
                                        capture_output=True, text=True).stdout):
        if si["properties"].get("application.name") == app:
            return sinks.get(si["sink"])
    return None


tmp = Path(tempfile.mkdtemp())
with wave.open(str(tmp / "quiet.wav"), "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
    w.writeframes((np.zeros(48000 * 12 * 2)).astype("<i2").tobytes())

mods = [null_sink("resona_cap_hw"), null_sink("resona_cap_other")]
app = QApplication(sys.argv)
players = []
b = Backend()
try:
    check(wait_for(lambda: b.running), "engine started on the stand-in hardware sink")
    # like FMOD: connect to the hardware device by name, not to the default
    players.append(subprocess.Popen(["paplay", "-d", "resona_cap_hw", "--client-name=FakeWarThunder",
                                     "--property=application.name=FakeWarThunder", str(tmp / "quiet.wav")]))
    # a user's deliberate routing to another device must be respected
    players.append(subprocess.Popen(["paplay", "-d", "resona_cap_other", "--client-name=OtherDevApp",
                                     "--property=application.name=OtherDevApp", str(tmp / "quiet.wav")]))
    check(wait_for(lambda: sink_of("FakeWarThunder") == "resona_cap_sink"),
          f"direct-to-hardware stream rerouted through Resona (now on {sink_of('FakeWarThunder')})")
    pump(1.5)
    check(sink_of("OtherDevApp") == "resona_cap_other",
          f"stream deliberately on another device left alone ({sink_of('OtherDevApp')})")
    out_on = sink_of("resona_cap_sink")  # engine output is not a regular app; must not be moved
    check(out_on is None, "Resona's own output stream was not touched")
    hb = b.shm.heartbeat
    check(wait_for(lambda: b.shm.heartbeat > hb, 3), "engine is processing the captured game audio")

    b.setCaptureAll(False)
    players.append(subprocess.Popen(["paplay", "-d", "resona_cap_hw", "--client-name=SecondGame",
                                     "--property=application.name=SecondGame", str(tmp / "quiet.wav")]))
    pump(2.5)
    check(sink_of("SecondGame") == "resona_cap_hw", "with the setting off, direct streams stay where they are")
finally:
    for p in players:
        p.terminate()
    b.shutdown()
    for m in mods:
        subprocess.run(["pactl", "unload-module", m])
    print("ALL PASSED" if not fails else f"FAILED ({fails})")
    sys.exit(1 if fails else 0)
