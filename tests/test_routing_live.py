"""Live routing test: default-sink takeover, device following, volume sync, restore.

Briefly changes the system default output; always restores it.
    python3 tests/test_routing_live.py
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="resona-cfg-")
os.environ.setdefault("RESONA_SINK_NAME", "resona_rt_sink")  # never collide with a running Resona
os.environ["RESONA_SHM"] = tempfile.mktemp(prefix="resona-shm-")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from resona import pipeline  # noqa: E402
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


def wait_for(cond, secs=6.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        pump(0.1)
        if cond():
            return True
    return False


app = QApplication(sys.argv)
original = pipeline.default_sink()
hw = [s.name for s in pipeline.list_sinks()]
print("original default:", original, "| hardware sinks:", len(hw))
b = Backend()
try:
    check(wait_for(lambda: b.running), "engine started")
    check(pipeline.default_sink() == pipeline.SINK_NAME, "Resona became the default output")
    check(b.pipe.target == original, f"engine plays into the previous default ({b.pipe.target})")

    subprocess.run(["pactl", "set-sink-volume", pipeline.SINK_NAME, "50%"])
    check(wait_for(lambda: abs(b.params["sysvol_db"] - (-18.06)) < 0.5),
          f"volume change reached the engine (sysvol_db={b.params['sysvol_db']:.2f}, expect -18.06)")
    subprocess.run(["pactl", "set-sink-volume", pipeline.SINK_NAME, "100%"])

    others = [s for s in hw if s != original]
    if others:
        other = others[0]
        subprocess.run(["pactl", "set-default-sink", other])  # user picks another device in the tray
        check(wait_for(lambda: b.pipe.target == other and b.running and not b.busy, 10),
              f"followed system output switch to {other}")
        check(wait_for(lambda: pipeline.default_sink() == pipeline.SINK_NAME, 4),
              "Resona reclaimed the default after following")
        b.setOutput(original)
        check(wait_for(lambda: b.pipe.target == original and b.running and not b.busy, 10),
              "switched back via setOutput()")
    else:
        print("  skip only one output device; follow test skipped")
finally:
    pump(0.5)
    b.shutdown()
    time.sleep(0.5)
    now = pipeline.default_sink()
    check(now == original, f"default restored on quit ({now})")
    if now != original:
        pipeline.set_default_sink(original)
    check(not pipeline.sink_exists(pipeline.SINK_NAME), "virtual sink removed on quit")
    print("ALL PASSED" if not fails else f"FAILED ({fails})")

sys.exit(1 if fails else 0)
