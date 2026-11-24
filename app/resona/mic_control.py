"""QML-facing controller for Resona Microphone (exposed as `audio.mic`)."""
from __future__ import annotations

import math
import os
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, Signal, Slot

from . import mic

TEST_SECONDS = 4.0


def sanitize(cfg) -> dict:
    """Saved mic settings; anything malformed falls back to defaults instead of failing the load."""
    cfg = cfg if isinstance(cfg, dict) else {}
    params = dict(mic.DEFAULTS)
    if isinstance(cfg.get("params"), dict):
        params.update(mic.clamp_params(cfg["params"]))
    return {"on": cfg.get("on") is True, "default": cfg.get("default", True) is not False,
            "source": cfg["source"] if isinstance(cfg.get("source"), str) else "",
            "params": params}


class MicController(QObject):
    changed = Signal()
    metersChanged = Signal()
    toast = Signal(str)

    def __init__(self, state: dict, run_async, touch, parent=None):
        super().__init__(parent)
        self._state = state
        self._cfg = sanitize(state.get("mic"))
        state["mic"] = self._cfg
        self._async = run_async
        self._touch = touch
        self.shm = mic.MicState()
        self.shm.write(self._cfg["params"])
        self.pipe = mic.MicPipeline(self.shm.path)
        self._closing = False
        self._busy = False
        self._running = False
        self._status = "Off"
        self._sources: list[dict] = []
        self._meters = {"in": 0.0, "out": 0.0, "nr": 0.0, "agc": 0.0}
        self._last_hb, self._last_hb_change, self._active = 0, 0.0, False
        self._restarts = 0
        self._quiet_until = 0.0
        self._test = "idle"
        rt = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/resona-{os.getuid()}"
        self._test_file = Path(rt) / "resona" / "mic-test.wav"

    # ------------------------------------------------------------------ lifecycle
    def begin(self):
        self.refreshSources()
        if self._cfg["on"]:
            self._start()

    def close(self):
        if self._closing:
            return
        self._closing = True
        self.pipe.stop(restore_default=True)
        self.shm.close()

    def _pick_source(self) -> str:
        names = [s["name"] for s in self._sources]
        if self._cfg["source"] in names:
            return self._cfg["source"]
        cur = mic.default_source()
        if cur in names:
            return cur
        if self.pipe.previous_default in names:
            return self.pipe.previous_default
        return names[0] if names else ""

    def _start(self, make_default: bool | None = None):
        if self._closing or self._busy:
            return
        if not self._sources:
            self._sources = mic.list_sources()
        source = self._pick_source()
        if not source:
            self._set_status("No microphone found")
            return
        self._busy = True
        self._set_status("Starting…")
        try:
            self.pipe.spawn(source)          # main thread
        except (OSError, FileNotFoundError) as e:
            self._busy = False
            self._set_status(f"Could not start: {e}")
            return
        if make_default is None:
            make_default = self._cfg["default"]
        self._async(lambda: self.pipe.wait_ready(make_default), self._started)

    def _started(self, ok):
        self._busy = False
        if self._closing:
            return
        if not self._cfg["on"]:
            self.pipe.stop(restore_default=True)
            self._set_status("Off")
            return
        if isinstance(ok, Exception) or not ok:
            log = [line for line in self.pipe.last_log().splitlines() if line.strip()]
            self.pipe.stop(restore_default=True)
            self._running = False
            self._set_status("Microphone engine failed to start" + (f": {log[-1]}" if log else ""))
            return
        self._running = True
        self._quiet_until = time.monotonic() + 1.5   # our own node swap settles before we read defaults
        self._set_status("Ready")

    def _stop(self):
        self.pipe.stop(restore_default=True)
        self._running = False
        self._active = False
        self._set_status("Off")

    def _set_status(self, text: str):
        self._status = text
        self.changed.emit()

    # ------------------------------------------------------------------ periodic (from Backend._tick)
    def tick(self, visible: bool):
        if self._closing or not self._running:
            return
        if not self.pipe.running and not self._busy:
            self._running = False
            if self._restarts < 3:
                self._restarts += 1
                self.toast.emit("Microphone engine stopped, restarting")
                self._start()
            else:
                self._set_status("Microphone engine keeps stopping, see logs")
            return
        hb, now = self.shm.heartbeat, time.monotonic()
        if hb != self._last_hb:
            self._last_hb, self._last_hb_change = hb, now
        active = now - self._last_hb_change < 0.5
        if active != self._active:
            self._active = active
            self._set_status("Processing your voice" if active else "Ready")
        if not visible:
            return
        m = self.shm.meters() if active else dict(in_peak=0.0, out_peak=0.0, nr_db=0.0, agc_db=0.0)

        def lvl(p):
            return max(0.0, min(1.0, (20 * math.log10(max(p, 1e-6)) + 60) / 60))
        new = {"in": round(lvl(m["in_peak"]), 3), "out": round(lvl(m["out_peak"]), 3),
               "nr": round(m["nr_db"], 1), "agc": round(m["agc_db"], 1)}
        if new != self._meters:
            self._meters = new
            self.metersChanged.emit()

    def sources_changed(self):
        """Capture devices or the system default input changed (USB mic, headset, system settings)."""
        def look():
            return mic.list_sources(), mic.default_source()

        def done(res):
            if self._closing or isinstance(res, Exception):
                return
            sources, default = res
            self._sources = sources
            self.changed.emit()
            if not self._running or self._busy:
                return
            names = [s["name"] for s in sources]
            if self.pipe.source not in names:
                self.toast.emit("Microphone unplugged, switching to another one")
                self._start(make_default=self.pipe.claimed_default)
            elif (time.monotonic() >= self._quiet_until and default in names and default != self.pipe.source
                  and (self.pipe.claimed_default or not self._cfg["source"])):
                # The user picked another microphone in the system settings. Respect it: never
                # take the default back. With "System default" as input, follow that microphone.
                self.pipe.claimed_default = False
                if not self._cfg["source"]:
                    desc = next((s["description"] for s in sources if s["name"] == default), default)
                    self.toast.emit(f"Resona Microphone now uses {desc}")
                    self._start(make_default=False)
        self._async(look, done)

    # ------------------------------------------------------------------ QML API
    @Property("QVariantMap", notify=changed)
    def info(self):
        return {"on": self._cfg["on"], "running": self._running, "busy": self._busy, "active": self._active,
                "status": self._status, "source": self.pipe.source if self._running else self._cfg["source"],
                "chosen": self._cfg["source"], "makeDefault": self._cfg["default"], "params": dict(self._cfg["params"]),
                "test": self._test}

    @Property("QVariantList", notify=changed)
    def sources(self):
        return self._sources

    @Property("QVariantMap", notify=metersChanged)
    def meters(self):
        return self._meters

    @Property("QVariantList", constant=True)
    def voices(self):
        return mic.VOICES

    @Slot()
    def refreshSources(self):
        self._sources = mic.list_sources()
        self.changed.emit()

    @Slot(bool)
    def setOn(self, on: bool):
        on = bool(on)
        if on == self._cfg["on"]:
            return
        self._cfg["on"] = on
        self._restarts = 0
        self._touch()
        if on:
            self._start()
        else:
            self._stop()
        self.changed.emit()

    @Slot(str)
    def setSource(self, name: str):
        """'' follows the system default microphone."""
        self._cfg["source"] = name
        self._touch()
        if self._running or self._busy:
            self._start()
        self.changed.emit()

    @Slot(bool)
    def setMakeDefault(self, on: bool):
        self._cfg["default"] = bool(on)
        self._touch()
        if self._running:
            if on:
                self.pipe.claim_default()
            else:
                self.pipe.release_default()
        self.changed.emit()

    @Slot(str, float)
    def setParam(self, name: str, value: float):
        clean = mic.clamp_params({name: value})
        if not clean or self._cfg["params"].get(name) == clean[name]:
            return
        self._cfg["params"].update(clean)
        self.shm.write(clean)
        self._touch()
        self.changed.emit()

    @Slot(int)
    def setVoice(self, index: int):
        """Pick a voice and start it at its natural pitch."""
        if not 0 <= index < len(mic.VOICES):
            return
        values = {"voice": index, "pitch": mic.VOICE_PITCH.get(mic.VOICES[index], 0)}
        self._cfg["params"].update(values)
        self.shm.write(values)
        self._touch()
        self.changed.emit()

    @Slot()
    def reset(self):
        self._cfg["params"] = dict(mic.DEFAULTS)
        self.shm.write(mic.DEFAULTS)
        self._touch()
        self.changed.emit()

    @Slot()
    def test(self):
        """Record a few seconds through Resona Microphone, then play them back."""
        if self._test != "idle" or not self._running:
            if not self._running:
                self.toast.emit("Turn on Resona Microphone first")
            return
        self._test = "recording"
        self.changed.emit()

        def record():
            return mic.record_test(TEST_SECONDS, self._test_file, self.pipe.mic_name)

        def recorded(ok):
            if self._closing:
                return
            if isinstance(ok, Exception) or not ok:
                self._test = "idle"
                self.toast.emit("Could not record from the microphone")
                self.changed.emit()
                return
            self._test = "playing"
            self.changed.emit()
            self._async(lambda: mic.play_file(self._test_file), played)

        def played(_):
            if self._closing:
                return
            self._test = "idle"
            try:
                self._test_file.unlink()
            except OSError:
                pass
            self.changed.emit()
        self._async(record, recorded)
