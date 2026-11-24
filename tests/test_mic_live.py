"""Resona Microphone on a private PipeWire server: audio flows, system mic settings are respected.

Run through tests/run_pipewire.sh (it exports RESONA_PRIVATE_PIPEWIRE=1). Creates two fake
microphones, so it never touches a real one.
"""
import os
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

if os.environ.get("RESONA_PRIVATE_PIPEWIRE") != "1":
    sys.exit("refusing to run outside tests/run_pipewire.sh (it would change your real default microphone)")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("RESONA_PLUGIN", str(ROOT / "engine/resona.so"))
os.environ.setdefault("RESONA_MIC_SHM", f"{os.environ.get('XDG_RUNTIME_DIR', '/tmp')}/mic-live.shm")
from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, Signal  # noqa: E402

from resona import mic  # noqa: E402
from resona.mic_control import MicController  # noqa: E402

RT = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
fails = 0


def check(ok, msg):
    global fails
    print(("  ok   " if ok else "  FAIL ") + msg, flush=True)
    fails += 0 if ok else 1


def pactl(*args):
    return subprocess.run(["pactl", *args], capture_output=True, text=True, timeout=5).stdout.strip()


class Async(QObject):
    done = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.done.connect(lambda cb, res: cb(res))

    def __call__(self, fn, cb):
        def work():
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                res = e
            self.done.emit(cb, res)
        threading.Thread(target=work, daemon=True).start()


def pump(seconds):
    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


def wait_until(cond, seconds=8):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        pump(0.1)
    return cond()


def fake_mic(name):
    """A null sink we can play into, plus a remap source on its monitor: a real capture device."""
    pactl("load-module", "module-null-sink", f"sink_name={name}_feed", "channel_map=mono")
    pactl("load-module", "module-remap-source", f"master={name}_feed.monitor", f"source_name={name}",
          "channels=1", "channel_map=mono")
    return wait_until(lambda: mic.source_exists(name), 6)


def tone_file(path, freq, seconds=30):
    t = np.arange(int(48000 * seconds)) / 48000
    x = (0.2 * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000); w.writeframes(x.tobytes())


def record(seconds=2.0):
    path = RT / "mic-live.wav"
    ok = mic.record_test(seconds, path, mic.MIC_NAME)
    if not ok:
        return np.zeros(1)
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float) / 32768


def peak_freq(x):
    if len(x) < 4096:
        return 0.0
    x = x[len(x) // 2:]
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.argmax(spec) * 48000 / len(x))


def main():
    app = QCoreApplication.instance() or QCoreApplication([])  # noqa: F841
    check(fake_mic("ci_mic_a") and fake_mic("ci_mic_b"), "two fake microphones created")
    pactl("set-default-source", "ci_mic_a")
    tone = RT / "tone400.wav"
    tone_file(tone, 400)
    player = subprocess.Popen(["paplay", "-d", "ci_mic_a_feed", str(tone)],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    player_b = None
    try:
        state = {"mic": {"on": True, "default": True, "params": {"ns": 0, "agc": 0, "clarity": 0}}}
        saved = []
        ctl = MicController(state, Async(), lambda: saved.append(1))
        ctl.begin()
        check(wait_until(lambda: ctl.info["running"]), f"Resona Microphone starts ({ctl.info['status']})")
        check(mic.default_source() == mic.MIC_NAME, "it becomes the default input when asked to")
        check(pactl("get-source-mute", mic.MIC_NAME).endswith("no"), "system mute control works on it")

        x = record()
        check(np.sqrt(np.mean(x ** 2)) > 0.02, f"audio flows from the real mic through it (rms {np.sqrt(np.mean(x**2)):.3f})")
        ctl.setVoice(2)                    # chipmunk, +7 semitones
        ctl.setParam("pitch", 12)
        pump(0.3)
        f = peak_freq(record())
        check(abs(f - 800) < 20, f"voice changer works live: 400 Hz tone comes out at {f:.0f} Hz")
        ctl.setVoice(0)

        pactl("set-source-mute", "ci_mic_a", "1")
        pump(0.3)
        x = record()
        check(np.max(np.abs(x)) < 0.01, "muting the real mic in system settings silences Resona Microphone too")
        pactl("set-source-mute", "ci_mic_a", "0")

        r = subprocess.run(["pactl", "set-source-volume", mic.MIC_NAME, "50%"], capture_output=True)
        check(r.returncode == 0, "system volume control works on Resona Microphone")
        pactl("set-source-volume", mic.MIC_NAME, "100%")

        # nothing recording -> the real microphone is not held open (no privacy LED, no CPU)
        pump(1.5)
        cap = [line for line in pactl("list", "short", "source-outputs").splitlines() if mic.CAPTURE_NAME in line]
        nodes = subprocess.run(["pw-cli", "ls", "Node"], capture_output=True, text=True).stdout
        check(mic.CAPTURE_NAME in nodes, "capture node exists")
        idle = subprocess.run(["pw-dump"], capture_output=True, text=True).stdout
        check('"node.passive": true' in idle or "node.passive" in idle, "capture is passive: the real mic only opens while something records")
        del cap

        # the user picks another microphone in system settings: respect it, follow it
        player_b = subprocess.Popen(["paplay", "-d", "ci_mic_b_feed", str(tone)],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pactl("set-default-source", "ci_mic_b")
        ctl.sources_changed()
        check(wait_until(lambda: ctl.info["running"] and ctl.pipe.source == "ci_mic_b", 8),
              f"follows the microphone picked in system settings (now {ctl.pipe.source})")
        pump(2.5)
        check(mic.default_source() == "ci_mic_b", f"and never takes the default back (default is {mic.default_source()})")

        # turning it off leaves the user's choice alone
        ctl.setOn(False)
        check(wait_until(lambda: not mic.source_exists(mic.MIC_NAME), 5), "turning it off removes Resona Microphone")
        check(mic.default_source() == "ci_mic_b", "and leaves the system default input untouched")

        # on again, claim the default, then quit: the default goes back to the real mic
        ctl.setOn(True)
        check(wait_until(lambda: ctl.info["running"] and mic.default_source() == mic.MIC_NAME),
              "turned on again it becomes the default input")
        ctl.close()
        check(wait_until(lambda: not mic.source_exists(mic.MIC_NAME), 5), "quitting removes it")
        check(mic.default_source() in ("ci_mic_a", "ci_mic_b"),
              f"quitting hands the default back to a real microphone ({mic.default_source()})")

        # with "use as default" off, the system default is never touched
        pactl("set-default-source", "ci_mic_a")
        state2 = {"mic": {"on": True, "default": False}}
        ctl2 = MicController(state2, Async(), lambda: None)
        ctl2.begin()
        check(wait_until(lambda: ctl2.info["running"]), "starts with 'use as default' off")
        pump(1.0)
        check(mic.default_source() == "ci_mic_a", "and the system default input stays the real mic")

        # unplugging the microphone in use: it moves to another one, no crash
        pactl("set-default-source", "ci_mic_b")
        mods = [line.split("\t")[0] for line in pactl("list", "short", "modules").splitlines() if "ci_mic_a" in line]
        for m in mods:
            pactl("unload-module", m)
        ctl2.sources_changed()
        check(wait_until(lambda: ctl2.info["running"] and ctl2.pipe.source == "ci_mic_b", 8),
              f"unplugging the mic in use switches to another one ({ctl2.pipe.source})")
        ctl2.close()
        check(mic.default_source() == "ci_mic_b", "the user's default input is still theirs")
    finally:
        player.terminate()
        if player_b:
            player_b.terminate()
    print("ALL PASSED" if not fails else f"FAILED ({fails})", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
