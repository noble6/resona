"""QML-facing controller: engine lifecycle, presets, hardware, correction, persistence, analyzers."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Property, QObject, QProcess, QTimer, QUrl, Signal, Slot

from . import __version__, correction, correction_model, hardware, persistence, pipeline, presets, validation
from .shm import SharedState
from .desktop import exec_line
from .updates import UpdateController

AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "resona.desktop"

EQ_FREQS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
N_BANDS = 56
CURVE_FREQS = np.geomspace(20, 20000, 160)
ACCENTS = ["#8B5CF6", "#FF5E7E", "#22D3B6", "#FFB224", "#3BA9FF", "#FF7A45", "#A6E22E"]


def peaking_db(freqs, f0, gain, q=1.1, fs=48000.0):
    return correction.response_db([{"type": "PK", "freq": f0, "gain": gain, "q": q}], freqs, fs)


def is_laptop() -> bool:
    try:
        return int(Path("/sys/class/dmi/id/chassis_type").read_text().strip()) in (8, 9, 10, 14, 30, 31, 32)
    except (OSError, ValueError):
        return False


def to_path(url: str) -> str:
    return QUrl(url).toLocalFile() if str(url).startswith("file:") else str(url)


class Backend(QObject):
    paramsChanged = Signal()
    stateChanged = Signal()
    sinksChanged = Signal()
    spectrumChanged = Signal()
    metersChanged = Signal()
    curveChanged = Signal()
    hardwareChanged = Signal()
    correctionChanged = Signal()
    searchChanged = Signal()
    appsChanged = Signal()
    presetsChanged = Signal()
    updateChanged = Signal()
    toast = Signal(str)
    _startDone = Signal(bool, str)
    _call = Signal(object, object)  # (callback, result) marshalled to the GUI thread

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = self._load()
        self._state.setdefault("app_rules", dict(presets.APP_RULES_DEFAULT))
        self._params = dict(presets.DEFAULTS)
        self._params.update({k: v for k, v in self._state.get("params", {}).items() if k in presets.DEFAULTS})
        self._params["sysvol_db"] = 0
        self.shm = SharedState()
        self.shm.write(self._params)
        self.pipe = pipeline.Pipeline(self.shm.path)

        self._running = False
        self._busy = False
        self._quiet_until = 0.0
        self._status = "Starting engine…"
        self._sinks: list[dict] = []
        self._spec_in = [0.0] * N_BANDS
        self._spec_out = [0.0] * N_BANDS
        self._meters = {"in": 0.0, "out": 0.0, "leveler": 0.0, "limiter": 0.0, "loudness": 0.0}
        self._ieq = [0.0] * 10
        self._visuals = True
        self._last_hb = 0
        self._last_hb_change = 0.0
        self._processing = False
        self._restarts = 0
        self._ticks = 0
        self._curve = [0.0] * len(CURVE_FREQS)
        self._corr_curve = [0.0] * len(CURVE_FREQS)
        self._band_cache = None
        self._hw: list[dict] = []
        self._clock: dict = {}
        self._aeq_index: list[dict] | None = None
        self._results: list[dict] = []
        self._searching = False
        self._apps: list[dict] = []
        self._auto_base: dict | None = None
        self._auto_app = ""
        self._captured: set[str] = set()
        self._call.connect(lambda cb, res: cb(res))
        self._recompute_curve()
        self._push_correction()

        self._save_timer = QTimer(self, singleShot=True, interval=600, timeout=self._save)
        self._vol_timer = QTimer(self, singleShot=True, interval=60, timeout=self._sync_volume)
        self._evt_timer = QTimer(self, singleShot=True, interval=250, timeout=self._on_server_event)
        self._hw_timer = QTimer(self, singleShot=True, interval=700, timeout=self.refreshHardware)
        self._app_timer = QTimer(self, singleShot=True, interval=500, timeout=self._scan_apps)
        self._ir_timer = QTimer(self, singleShot=True, interval=700, timeout=self.startEngine)
        self._anim = QTimer(self, interval=33, timeout=self._tick)
        self._anim.start()
        self._watchdog = QTimer(self, interval=1500, timeout=self._check_engine)
        self._watchdog.start()
        self._startDone.connect(self._on_started)

        self._sub = QProcess(self)
        self._sub.readyReadStandardOutput.connect(self._on_pactl_event)
        if shutil.which("stdbuf"):  # pactl block-buffers when piped
            self._sub.start("stdbuf", ["-oL", "pactl", "subscribe"])
        else:
            self._sub.start("pactl", ["subscribe"])

        self._refresh_sinks()
        self.refreshHardware()
        QTimer.singleShot(0, self.startEngine)
        QTimer.singleShot(1500, self._scan_apps)

        self._updates = UpdateController(self._state, self._async, self._touch,
                                         lambda: self._processing, lambda: self._visuals, self)
        self._updates.updateChanged.connect(self.updateChanged)
        self._updates.toast.connect(self.toast)

    # ------------------------------------------------------------------ helpers
    def _async(self, fn, done):
        def work():
            try:
                res = fn()
            except Exception as e:  # noqa: BLE001
                res = e
            self._call.emit(done, res)
        threading.Thread(target=work, daemon=True).start()

    def _load(self) -> dict:
        return persistence.load_state()

    def _save(self):
        self._state["params"] = {k: v for k, v in self._params.items() if k not in ("sysvol_db", "layout")}
        if self._auto_base:  # never persist a temporary per-app profile
            self._state["params"] = self._auto_base["params"]
        try:
            persistence.save_state(self._state)
        except (OSError, TypeError, ValueError) as e:
            print("resona: could not save state:", e, file=sys.stderr)

    def _touch(self):
        self._save_timer.start()

    def _snapshot(self) -> dict:
        return {"params": {k: self._params[k] for k in presets.SOUND_KEYS},
                "profile": self.profile, "device": self.deviceMode, "modified": self.modified,
                "eq_preset": self.eqPreset}

    def _restore(self, snap: dict):
        self._state["profile"] = snap.get("profile", "Dynamic")
        self._state["device"] = snap.get("device", "headphones")
        self._state["modified"] = snap.get("modified", False)
        self._state["eq_preset"] = snap.get("eq_preset", "Flat")
        self._apply({k: v for k, v in snap.get("params", {}).items() if k in presets.SOUND_KEYS})
        self.stateChanged.emit()

    # ------------------------------------------------------------------ engine
    @Slot()
    def startEngine(self):
        if self._busy:
            self._ir_timer.start()  # try again once the current start settles
            return
        target = self._pick_target()
        layout = hardware.layout_of(pipeline.sink_channel_map(target)) if target else hardware.layout_of("")
        ir = None
        if self._state.get("ir") and self._state["ir"].get("on"):
            ir = dict(self._state["ir"])
            if not Path(ir["path"]).exists():
                ir = None
        self._params["layout"] = layout["bits"]
        self.shm.write({"layout": layout["bits"]})
        self._busy = True
        self._quiet_until = time.monotonic() + 3
        self._status = "Starting engine…"
        self.stateChanged.emit()
        try:
            self.pipe.spawn(target, layout=layout, ir=ir)  # main thread on purpose, see Pipeline.spawn
        except Exception as e:  # noqa: BLE001
            self._startDone.emit(False, str(e))
            return

        def work():
            ok = self.pipe.wait_ready(make_default=not os.environ.get("RESONA_TEST_TARGET"))
            self._startDone.emit(ok, target or "")
        threading.Thread(target=work, daemon=True).start()

    def _on_started(self, ok: bool, info: str):
        self._busy = False
        self._quiet_until = time.monotonic() + 1.5
        self._running = ok
        if ok:
            prev = self._state.get("last_target")
            if info and prev != info:
                self._device_switched(prev, info)
            self._state["output"] = info
            self._state["last_target"] = info
            self._status = "Ready"
            self._touch()
            self._sync_volume()
            self._app_timer.start()
        else:
            log = self.pipe.last_log().strip().splitlines()
            self._status = "Engine failed to start" + (f": {log[-1]}" if log else (f": {info}" if info else ""))
            self.toast.emit(self._status)
        self.stateChanged.emit()

    def _device_switched(self, old: str | None, new: str):
        """Lunaris-style per-device memory: each output keeps its own sound."""
        if not self._state.get("per_device", True) or self._auto_base:
            return
        mem = self._state.setdefault("device_memory", {})
        if old:
            mem[old] = self._snapshot()
        if new in mem:
            self._restore(mem[new])
            desc = next((s["description"] for s in self._sinks if s["name"] == new), new)
            self.toast.emit(f"Restored your sound for {desc}")
        elif self._state.get("last_target") is not None:
            kind = next((s["kind"] for s in self._sinks if s["name"] == new), "speakers")
            mode = "headphones" if kind in ("headphones", "bluetooth") else \
                   ("laptop" if kind == "speakers" and is_laptop() else "speakers")
            if mode != self.deviceMode:
                self._state["device"] = mode
                self.applyProfile(self.profile)

    def _pick_target(self) -> str | None:
        if os.environ.get("RESONA_TEST_TARGET"):
            return os.environ["RESONA_TEST_TARGET"]
        names = [s["name"] for s in self._sinks]
        want = self._state.get("output")
        if want in names:
            return want
        if want:  # e.g. the card profile changed: prefer a sink on the same card
            card = want.rsplit(".", 1)[0]
            same = [n for n in names if n.rsplit(".", 1)[0] == card]
            if same:
                return same[0]
        cur = pipeline.default_sink()
        if cur in names:
            return cur
        return names[0] if names else None

    def _check_engine(self):
        if self._busy:
            return
        if self._running and not self.pipe.running:
            self._running = False
            if self._restarts < 5:
                self._restarts += 1
                self.toast.emit("Engine stopped unexpectedly, restarting")
                self.startEngine()
            else:
                self._status = "Engine keeps crashing, see logs"
                self.stateChanged.emit()

    def shutdown(self):
        # stop every timer first: a late animation tick would read the shm after it is unmapped
        self._updates.close()
        for t in (self._anim, self._watchdog, self._app_timer,
                  self._hw_timer, self._evt_timer, self._vol_timer, self._ir_timer):
            t.stop()
        if self._auto_base:
            self._restore(self._auto_base)
            self._auto_base = None
        self._save_timer.stop()
        if self._state.get("per_device", True) and self.pipe.target:
            self._state.setdefault("device_memory", {})[self.pipe.target] = self._snapshot()
        self._save()
        self._sub.kill()
        self._sub.waitForFinished(500)
        self.pipe.stop(restore_default=True)
        self.shm.close()

    # ------------------------------------------------------------------ pactl events
    def _on_pactl_event(self):
        data = bytes(self._sub.readAllStandardOutput()).decode(errors="replace")
        for line in data.splitlines():
            if " on sink #" in line and "'change'" in line:
                self._vol_timer.start()
            elif " on server" in line or ("'new'" in line or "'remove'" in line) and " on sink #" in line:
                self._evt_timer.start()
            if " on card #" in line or (" on sink #" in line and "'change'" not in line):
                self._hw_timer.start()
            if " on sink-input #" in line and ("'new'" in line or "'remove'" in line):
                self._app_timer.start()

    def _sync_volume(self):
        if not self._running:
            return
        db = pipeline.sink_volume_db(self.pipe.sink_name)
        if db is not None and abs(db - self._params.get("sysvol_db", 0)) > 0.01:
            self._params["sysvol_db"] = max(-120.0, min(0.0, db))
            self.shm.write({"sysvol_db": self._params["sysvol_db"]})

    def _on_server_event(self):
        self._refresh_sinks()
        if not self._running and not self._busy:
            return
        wait = self._quiet_until - time.monotonic()
        if self._busy or wait > 0:  # our own routing changes are settling: look again later
            self._evt_timer.start(int(max(wait, 0.3) * 1000) + 50)
            return
        if os.environ.get("RESONA_TEST_TARGET"):
            return
        names = {s["name"] for s in self._sinks}
        if self.pipe.target and self.pipe.target not in names:  # target vanished (profile switch, unplug)
            self.startEngine()
            return
        layout = hardware.layout_of(pipeline.sink_channel_map(self.pipe.target or ""))
        if self.pipe.layout and layout["channels"] != self.pipe.layout.get("channels"):
            self.startEngine()
            return
        cur = pipeline.default_sink()
        if cur and cur != self.pipe.sink_name and cur in names:
            if self._state.get("follow", True):
                if cur != self.pipe.target:
                    self._state["output"] = cur
                    desc = next((s["description"] for s in self._sinks if s["name"] == cur), cur)
                    self.toast.emit(f"Now playing through {desc}")
                    self.startEngine()
                else:
                    self._quiet_until = time.monotonic() + 1.0
                    pipeline.set_default_sink(self.pipe.sink_name)

    def _refresh_sinks(self):
        sinks = [s.as_dict() for s in pipeline.list_sinks()]
        if sinks != self._sinks:
            self._sinks = sinks
            self.sinksChanged.emit()

    # ------------------------------------------------------------------ per-app profiles
    def _scan_apps(self):
        out = pipeline._run("pactl", "-f", "json", "list", "sink-inputs")
        try:
            inputs = json.loads(out or "[]")
        except json.JSONDecodeError:
            return
        self._capture_bypass(inputs)
        rules = self._state.get("app_rules", {})
        apps, seen = [], set()
        for si in inputs:
            p = si.get("properties", {})
            binary = (p.get("application.process.binary") or "").lower()
            name = p.get("application.name") or binary
            if not binary or binary.startswith("resona") or p.get("node.name", "").startswith("resona") \
                    or "pipewire" in binary or binary in seen:
                continue
            seen.add(binary)
            key = binary if binary in rules else (name or "").lower()
            apps.append({"binary": binary, "name": name, "profile": rules.get(key, ""),
                         "corked": bool(si.get("corked"))})
        if apps != self._apps:
            self._apps = apps
            self.appsChanged.emit()
        if not self._state.get("app_auto", True):
            return
        live = [a for a in apps if a["profile"] and not a["corked"]]
        if live:
            app = live[-1]
            if app["profile"] != self.profile or self._auto_app != app["binary"]:
                if not self._auto_base:
                    self._auto_base = self._snapshot()
                self._auto_app = app["binary"]
                self._state["profile"] = app["profile"]
                self._state["modified"] = False
                self._apply(presets.profile_params(app["profile"], self.deviceMode))
                self.stateChanged.emit()
                self.toast.emit(f"{app['profile']} profile for {app['name']}")
        elif self._auto_base:
            base, self._auto_base, self._auto_app = self._auto_base, None, ""
            self._restore(base)

    def _capture_bypass(self, inputs: list):
        """Route apps that open the hardware output directly back through Resona.

        Games using FMOD/Wwise PulseAudio backends (War Thunder, many Proton titles)
        enumerate sinks and connect to the first device by name instead of the
        default. Those streams skip every effect and ignore the volume keys, which
        act on the default (Resona) sink. Only streams sitting on the exact device
        Resona plays into are moved, so deliberate routing to another output stays.
        """
        if not self._running or self._busy or not self._state.get("capture_all", True):
            return
        target = self.pipe.target
        if not target:
            return
        try:
            sinks = json.loads(pipeline._run("pactl", "-f", "json", "list", "sinks") or "[]")
        except json.JSONDecodeError:
            return
        target_idx = next((s["index"] for s in sinks if s.get("name") == target), None)
        if target_idx is None:
            return
        moved = []
        for si in inputs:
            p = si.get("properties", {})
            if si.get("sink") != target_idx:
                continue
            if p.get("node.name", "").startswith("resona") or p.get("node.name") == self.pipe.out_name:
                continue  # our own engine output
            if p.get("node.dont-move") == "true":
                continue
            r = subprocess.run(["pactl", "move-sink-input", str(si["index"]), self.pipe.sink_name],
                               capture_output=True, timeout=3)
            if r.returncode == 0:
                moved.append(p.get("application.name") or p.get("application.process.binary") or "An app")
        for name in dict.fromkeys(moved):
            if name not in self._captured:
                self._captured.add(name)
                self.toast.emit(f"{name} was bypassing Resona. Routed it through, volume keys work now")

    @Property(bool, notify=stateChanged)
    def captureAll(self):
        return self._state.get("capture_all", True)

    @Slot(bool)
    def setCaptureAll(self, on: bool):
        self._state["capture_all"] = on
        self.stateChanged.emit()
        self._touch()
        if on:
            self._scan_apps()

    @Property("QVariantList", notify=appsChanged)
    def apps(self):
        return self._apps

    @Property(str, notify=stateChanged)
    def autoApp(self):
        return self._auto_app

    @Slot(str, str)
    def setAppRule(self, binary: str, profile: str):
        rules = self._state.setdefault("app_rules", {})
        if profile:
            rules[binary] = profile
        else:
            rules.pop(binary, None)
        self._touch()
        self._scan_apps()

    @Property(bool, notify=stateChanged)
    def appAuto(self):
        return self._state.get("app_auto", True)

    @Slot(bool)
    def setAppAuto(self, on: bool):
        self._state["app_auto"] = on
        if not on and self._auto_base:
            base, self._auto_base, self._auto_app = self._auto_base, None, ""
            self._restore(base)
        self.stateChanged.emit()
        self._touch()
        self._scan_apps()

    @Property(bool, notify=stateChanged)
    def perDevice(self):
        return self._state.get("per_device", True)

    @Slot(bool)
    def setPerDevice(self, on: bool):
        self._state["per_device"] = on
        self.stateChanged.emit()
        self._touch()

    # ------------------------------------------------------------------ hardware
    @Slot()
    def refreshHardware(self):
        def scan():
            return hardware.scan(), hardware.clock_settings()

        def done(res):
            if isinstance(res, Exception):
                return
            self._hw, self._clock = res
            self.hardwareChanged.emit()
        self._async(scan, done)

    @Property("QVariantList", notify=hardwareChanged)
    def hardware(self):
        return self._hw

    @Property("QVariantMap", notify=hardwareChanged)
    def clock(self):
        return self._clock

    @Property(bool, notify=hardwareChanged)
    def hiRes(self):
        return hardware.hires_enabled()

    @Property(bool, notify=hardwareChanged)
    def hqResampler(self):
        return hardware.hq_resampler_enabled()

    @Property(bool, constant=True)
    def laptop(self):
        return is_laptop()

    @Slot(str, str)
    def setCardProfile(self, card: str, profile: str):
        if hardware.set_profile(card, profile):
            self.toast.emit("Output mode changed, Resona is re-routing")
            self._hw_timer.start()
            self._evt_timer.start(900)
        else:
            self.toast.emit("That output mode isn't available right now")

    @Slot(bool)
    def setHiRes(self, on: bool):
        max_rate = max([s["maxRate"] for c in self._hw for s in c["sinks"] if s["name"] == self.output] or [192000])
        rates = hardware.set_hires(on, max_rate)
        self.toast.emit(f"Hi-Res on: native {', '.join(f'{r/1000:g}' for r in rates)} kHz, no resampling"
                        if on else "Hi-Res off: everything runs at 48 kHz")
        self._hw_timer.start()

    @Slot(bool)
    def setHqResampler(self, on: bool):
        hardware.set_hq_resampler(on)
        self.toast.emit("Studio-grade resampling applies after an audio restart")
        self.hardwareChanged.emit()

    @Slot()
    def restartAudio(self):
        self.toast.emit("Restarting the audio system…")
        self._running = False
        self.pipe.stop(restore_default=False)
        hardware.restart_audio()
        QTimer.singleShot(3500, self.startEngine)
        QTimer.singleShot(3500, self.refreshHardware)

    @Slot(str, result="QVariantList")
    def btCodecs(self, card: str):
        return hardware.bt_codecs(card)

    @Slot(str, str)
    def setBtCodec(self, card: str, codec: str):
        ok = hardware.bt_switch_codec(card, codec)
        self.toast.emit(f"Bluetooth codec: {codec.upper()}" if ok else "Codec switch failed")
        self._hw_timer.start()

    # ------------------------------------------------------------------ correction
    def _push_correction(self):
        fs = self.shm.sample_rate
        self._corr_rate = fs
        prepared = correction_model.prepare(self._state.get("correction"), fs, CURVE_FREQS,
                                             self._params.get("corr_on", 0))
        if prepared.warning:
            self.toast.emit(prepared.warning)
        self.shm.write_corr(prepared.filters)
        self.shm.write({"corr_on": prepared.enabled})
        self._corr_curve = prepared.curve
        self.correctionChanged.emit()

    def _set_correction(self, info: dict):
        info = validation.correction(info)
        if info is None:
            raise ValueError("empty correction")
        self._state["correction"] = info
        self._apply({"corr_on": 1, "corr_preamp": info.get("preamp", 0)})
        self._push_correction()
        self._touch()

    @Property("QVariantMap", notify=correctionChanged)
    def correction(self):
        return correction_model.describe(self._state.get("correction"))

    @Property("QVariantList", notify=correctionChanged)
    def correctionCurve(self):
        return self._corr_curve

    @Slot(str)
    def searchAutoEq(self, query: str):
        if self._aeq_index is None:
            if self._searching:
                return
            self._searching = True
            self.searchChanged.emit()

            def done(res):
                self._searching = False
                if isinstance(res, Exception) or not res:
                    self.toast.emit("Couldn't reach the AutoEq database, check your connection")
                    self._aeq_index = None
                else:
                    self._aeq_index = res
                    self.searchAutoEq(query)
                self.searchChanged.emit()
            self._async(correction.autoeq_index, done)
            return
        self._results = correction.autoeq_search(self._aeq_index, query)
        self.searchChanged.emit()

    @Property("QVariantList", notify=searchChanged)
    def autoEqResults(self):
        return self._results

    @Property(bool, notify=searchChanged)
    def searching(self):
        return self._searching

    @Property(int, notify=searchChanged)
    def autoEqCount(self):
        return len(self._aeq_index or [])

    @Slot(int)
    def applyAutoEq(self, i: int):
        if not 0 <= i < len(self._results):
            return
        entry = self._results[i]
        self.toast.emit(f"Fetching {entry['name']}…")

        def done(res):
            if isinstance(res, Exception):
                self.toast.emit(f"Download failed: {res}")
                return
            try:
                pre, filters = correction.parse_parametric(res)
                if not filters:
                    self.toast.emit("That profile has no parametric EQ")
                    return
                self._set_correction({"name": entry["name"], "source": f"AutoEq · {entry['source']}",
                                      "kind": "parametric", "filters": filters, "preamp": pre})
            except ValueError as e:
                self.toast.emit(f"Invalid correction: {e}")
                return
            self.toast.emit(f"{entry['name']} corrected to the Harman target")
        self._async(lambda: correction.autoeq_fetch(entry), done)

    @Slot(str)
    def importCorrection(self, url: str):
        path = Path(to_path(url))
        try:
            info = correction_model.from_file(path, self.shm.sample_rate)
            self._set_correction(info)
        except (OSError, ValueError) as e:
            self.toast.emit(f"Import failed: {e}")
            return
        self.toast.emit(f"Loaded {path.name} · {len(info['filters'])} filters")

    @Slot()
    def clearCorrection(self):
        self._state.pop("correction", None)
        self._apply({"corr_on": 0, "corr_preamp": 0})
        self._push_correction()
        self._touch()

    # convolver
    @Property("QVariantMap", notify=correctionChanged)
    def ir(self):
        return self._state.get("ir") or {}

    @Slot(str)
    def loadIr(self, url: str):
        try:
            info = correction.read_ir(to_path(url))
        except (OSError, ValueError) as e:
            self.toast.emit(f"Impulse response: {e}")
            return
        old = self._state.get("ir") or {}
        info.update(on=True, mix=old.get("mix", 1.0), name=Path(info["path"]).stem)
        self._state["ir"] = info
        self.correctionChanged.emit()
        self._touch()
        self.toast.emit(f"Convolver: {info['name']} · {info['channels']} ch · {info['seconds']} s")
        self._ir_timer.start()

    @Slot(bool)
    def setIrOn(self, on: bool):
        if self._state.get("ir"):
            self._state["ir"]["on"] = on
            self.correctionChanged.emit()
            self._touch()
            self._ir_timer.start()

    @Slot(float)
    def setIrMix(self, mix: float):
        if self._state.get("ir"):
            self._state["ir"]["mix"] = round(mix, 2)
            self.correctionChanged.emit()
            self._touch()
            self._ir_timer.start()  # graph rebuild, debounced

    @Slot()
    def clearIr(self):
        if self._state.pop("ir", None):
            self.correctionChanged.emit()
            self._touch()
            self._ir_timer.start()

    # ------------------------------------------------------------------ user presets
    @Property("QVariantList", notify=presetsChanged)
    def userPresets(self):
        return persistence.user_presets()

    def _preset_path(self, name: str) -> Path:
        return persistence.preset_path(name)

    @Slot(str)
    def savePreset(self, name: str):
        if not name.strip():
            return
        try:
            data = {"resona_preset": 1, **self._snapshot(), "correction": self._state.get("correction")}
            persistence.write_json(self._preset_path(name), data)
        except (OSError, TypeError, ValueError) as e:
            self.toast.emit(f"Preset: {e}")
            return
        self.presetsChanged.emit()
        self.toast.emit(f"Saved “{name.strip()}”")

    def _load_preset_data(self, data: dict, name: str):
        if not isinstance(data, dict) or "params" not in data:
            raise ValueError("not a Resona preset")
        data = validation.snapshot(data)
        if data.get("correction"):
            self._set_correction(data["correction"])
        self._restore(data)
        if not data.get("correction"):
            self.clearCorrection()
        self.toast.emit(f"Loaded “{name}”")

    @Slot(str)
    def loadPreset(self, name: str):
        try:
            self._load_preset_data(persistence.read_json(self._preset_path(name)), name)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            self.toast.emit(f"Preset: {e}")

    @Slot(str)
    def deletePreset(self, name: str):
        persistence.delete_preset(name)
        self.presetsChanged.emit()

    @Slot(str)
    def importPreset(self, url: str):
        path = Path(to_path(url))
        try:
            data = persistence.import_preset(path, self._preset_path(path.stem))
            self._load_preset_data(data, path.stem)
            self.presetsChanged.emit()
        except (OSError, ValueError, json.JSONDecodeError) as e:
            self.toast.emit(f"Import failed: {e}")

    @Slot(str, str)
    def exportPreset(self, name: str, url: str):
        try:
            dest = Path(to_path(url))
            if dest.suffix != ".json":
                dest = dest.with_suffix(".json")
            persistence.copy_file(self._preset_path(name), dest)
            self.toast.emit(f"Exported to {dest.name}")
        except OSError as e:
            self.toast.emit(f"Export failed: {e}")

    # ------------------------------------------------------------------ analyzer
    def _bands(self, n: int, fs: int):
        key = (n, fs)
        if self._band_cache and self._band_cache[0] == key:
            return self._band_cache[1:]
        edges = np.geomspace(28, 18000, N_BANDS + 1)
        df = fs / n
        starts = np.clip((edges[:-1] / df).astype(int), 1, n // 2 - 1)
        centers = np.sqrt(edges[:-1] * edges[1:])
        tilt = 3.0 * np.log2(centers / 1000.0)
        win = np.hanning(n).astype(np.float32)
        self._band_cache = (key, starts, tilt, win, 2.0 / win.sum())
        return self._band_cache[1:]

    def _spectrum(self, x, starts, tilt, win, norm):
        mag = np.abs(np.fft.rfft(x * win)) * norm
        vals = np.maximum.reduceat(mag, starts)
        db = 20 * np.log10(vals + 1e-9) + tilt
        return np.clip((db + 78) / 72, 0, 1)

    def _tick(self):
        self._ticks += 1
        if self.shm.sample_rate != self._corr_rate:
            self._push_correction()
            self.stateChanged.emit()
        hb = self.shm.heartbeat
        now = time.monotonic()
        if hb != self._last_hb:
            self._last_hb, self._last_hb_change = hb, now
        processing = self._running and now - self._last_hb_change < 0.4
        if processing != self._processing:
            self._processing = processing
            self.stateChanged.emit()
        if not self._visuals:
            return
        if processing:
            n = 2048
            starts, tilt, win, norm = self._bands(n, self.shm.sample_rate)
            xi, xo = self.shm.latest(n)
            si = self._spectrum(xi, starts, tilt, win, norm)
            so = self._spectrum(xo, starts, tilt, win, norm)
            m = self.shm.meters()
        else:
            si = so = np.zeros(N_BANDS)
            m = dict(in_l=0, in_r=0, out_l=0, out_r=0, leveler_db=0, limiter_db=0, loudness_db=0)
        oi, oo = np.asarray(self._spec_in), np.asarray(self._spec_out)
        oi = np.where(si > oi, oi + (si - oi) * 0.6, oi + (si - oi) * 0.18)
        oo = np.where(so > oo, oo + (so - oo) * 0.6, oo + (so - oo) * 0.18)
        if np.abs(oo - np.asarray(self._spec_out)).max() > 1e-3 or np.abs(oi - np.asarray(self._spec_in)).max() > 1e-3:
            self._spec_in, self._spec_out = oi.round(4).tolist(), oo.round(4).tolist()
            self.spectrumChanged.emit()

        def lvl(p):
            return float(np.clip((20 * np.log10(max(p, 1e-6)) + 60) / 60, 0, 1))
        new = {
            "in": lvl(max(m["in_l"], m["in_r"])),
            "out": lvl(max(m["out_l"], m["out_r"])),
            "leveler": round(float(m["leveler_db"]), 1),
            "limiter": round(float(m["limiter_db"]), 1),
            "loudness": round(float(m["loudness_db"]), 1),
        }
        if self._ticks % 8 == 0:
            ieq = self.shm.ieq_gains()
            if ieq != self._ieq:
                self._ieq = ieq
                new["ieq"] = ieq
        new["ieq"] = self._ieq
        if new != self._meters:
            self._meters = new
            self.metersChanged.emit()

    # ------------------------------------------------------------------ EQ curve
    def _recompute_curve(self):
        total = np.zeros_like(CURVE_FREQS)
        if self._params.get("eq_on", 1):
            for f, i in zip(EQ_FREQS, range(10)):
                g = float(self._params.get(f"eq{i}", 0))
                if abs(g) > 1e-4:
                    total += peaking_db(CURVE_FREQS, f, g)
        self._curve = total.round(3).tolist()
        self.curveChanged.emit()

    # ------------------------------------------------------------------ QML API
    @Property("QVariantMap", notify=paramsChanged)
    def params(self):
        return self._params

    @Slot(str, float)
    def setParam(self, name: str, value: float):
        if name not in presets.DEFAULTS or self._params.get(name) == value:
            return
        try:
            validation.params({name: value})
        except ValueError:
            return
        self._params[name] = value
        self.shm.write({name: value})
        if name == "corr_on":
            self._push_correction()
        if name.startswith("eq"):
            self._recompute_curve()
        if name in presets.SOUND_KEYS and name not in ("preamp", "output") and not self._state.get("modified"):
            self._state["modified"] = True
            self.stateChanged.emit()
        self.paramsChanged.emit()
        self._touch()

    @Slot(str)
    def toggle(self, name: str):
        self.setParam(name, 0.0 if self._params.get(name, 0) else 1.0)

    @Slot(str)
    def setHeadphoneSpatial(self, mode: str):
        """off | xfeed | hrtf: mutually exclusive headphone renderers."""
        self._apply({"xfeed_on": 1 if mode == "xfeed" else 0, "hrtf_on": 1 if mode == "hrtf" else 0})
        self._state["modified"] = True
        self.stateChanged.emit()

    def _apply(self, values: dict):
        self._params.update(values)
        self.shm.write(values)
        if "corr_on" in values:
            self._push_correction()
        self._recompute_curve()
        self.paramsChanged.emit()
        self._touch()

    @Slot(str)
    def applyProfile(self, name: str):
        if self._auto_base:  # a manual choice ends the per-app override
            self._auto_base, self._auto_app = None, ""
        self._state["profile"] = name
        self._state["modified"] = False
        _, _, p = presets.PROFILES.get(name, presets.PROFILES["Dynamic"])
        self._state["eq_preset"] = p.get("eq", "Flat")
        self._apply(presets.profile_params(name, self.deviceMode))
        self.stateChanged.emit()

    @Slot(str)
    def setDeviceMode(self, mode: str):
        self._state["device"] = mode
        self.applyProfile(self.profile)

    @Slot(str)
    def applyEq(self, name: str):
        gains = presets.EQ_PRESETS.get(name)
        if gains:
            self._state["eq_preset"] = name
            self._apply({f"eq{i}": g for i, g in enumerate(gains)} | {"eq_on": 1})
            self.stateChanged.emit()

    @Slot()
    def resetEq(self):
        self.applyEq("Flat")

    @Slot(bool)
    def setEnabled(self, on: bool):
        self.setParam("enable", 1.0 if on else 0.0)

    @Slot(bool)
    def compare(self, hold: bool):
        self.shm.write({"enable": 0.0 if hold else float(self._params["enable"])})

    @Slot(str)
    def setOutput(self, name: str):
        if name and name != self.pipe.target:
            self._state["output"] = name
            self.startEngine()

    @Slot(bool)
    def setFollow(self, on: bool):
        self._state["follow"] = on
        self.stateChanged.emit()
        self._touch()

    @Slot(str)
    def setAccent(self, color: str):
        self._state["accent"] = color
        self.stateChanged.emit()
        self._touch()

    @Slot(bool)
    def setDark(self, dark: bool):
        self._state["dark"] = dark
        self.stateChanged.emit()
        self._touch()

    @Slot(bool)
    def setVisualsActive(self, on: bool):
        self._visuals = on

    @Property(bool, notify=stateChanged)
    def reducedMotion(self):
        return self._state.get("reduced_motion", False)

    @Slot(bool)
    def setReducedMotion(self, on: bool):
        self._state["reduced_motion"] = on
        self.stateChanged.emit()
        self._touch()

    # ------------------------------------------------------------------ updates
    @Slot()
    def checkUpdates(self):
        self._updates.checkUpdates()

    @Slot()
    def installUpdate(self, automatic: bool = False):
        self._updates.installUpdate(automatic=automatic)

    @Property("QVariantMap", notify=updateChanged)
    def updateInfo(self):
        return self._updates.updateInfo

    @Slot(str)
    def setUpdateFreq(self, freq: str):
        self._updates.setUpdateFreq(freq)

    @Slot(bool)
    def setUpdateAuto(self, on: bool):
        self._updates.setUpdateAuto(on)

    @Property(str, constant=True)
    def version(self):
        return __version__

    @Slot(bool)
    def setAutostart(self, on: bool):
        try:
            if on:
                AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
                launcher = shutil.which("resona")
                args = [launcher] if launcher else [sys.executable, str(Path(__file__).resolve().parents[1] / "main.py")]
                exe = exec_line(args + ["--hidden"])
                AUTOSTART.write_text(
                    "[Desktop Entry]\nType=Application\nName=Resona\n"
                    f"Exec={exe}\nIcon=resona\nX-GNOME-Autostart-enabled=true\n")
            elif AUTOSTART.exists():
                AUTOSTART.unlink()
        except OSError as e:
            self.toast.emit(f"Autostart: {e}")
        self.stateChanged.emit()

    @Property(bool, notify=stateChanged)
    def running(self):
        return self._running

    @Property(bool, notify=stateChanged)
    def busy(self):
        return self._busy

    @Property(bool, notify=stateChanged)
    def processing(self):
        return self._processing

    @Property(str, notify=stateChanged)
    def status(self):
        if self._running and self._status == "Ready":
            return "Processing" if self._processing else "Idle · waiting for audio"
        return self._status

    @Property(int, notify=stateChanged)
    def sampleRate(self):
        return self.shm.sample_rate

    @Property("QVariantMap", notify=stateChanged)
    def outputLayout(self):
        lay = self.pipe.layout or hardware.layout_of("")
        return {"name": lay["name"], "channels": lay["channels"], "positions": lay["positions"]}

    @Property(str, notify=stateChanged)
    def profile(self):
        return self._state.get("profile", "Dynamic")

    @Property(bool, notify=stateChanged)
    def modified(self):
        return bool(self._state.get("modified"))

    @Property(str, notify=stateChanged)
    def deviceMode(self):
        return self._state.get("device", "headphones")

    @Property(str, notify=stateChanged)
    def eqPreset(self):
        return self._state.get("eq_preset", "Flat")

    @Property(str, notify=stateChanged)
    def output(self):
        return self.pipe.target or self._state.get("output", "")

    @Property(bool, notify=stateChanged)
    def follow(self):
        return self._state.get("follow", True)

    @Property(str, notify=stateChanged)
    def accent(self):
        return self._state.get("accent", ACCENTS[0])

    @Property(bool, notify=stateChanged)
    def dark(self):
        return self._state.get("dark", True)

    @Property(bool, notify=stateChanged)
    def autostart(self):
        return AUTOSTART.exists()

    @Property("QVariantList", constant=True)
    def accents(self):
        return ACCENTS

    @Property("QVariantList", constant=True)
    def profiles(self):
        return [{"name": n, "desc": d, "shape": s} for n, (d, s, _) in presets.PROFILES.items()]

    @Property("QVariantList", constant=True)
    def eqPresets(self):
        return list(presets.EQ_PRESETS)

    @Property("QVariantList", constant=True)
    def ieqTargets(self):
        return presets.IEQ_TARGETS

    @Property("QVariantList", constant=True)
    def bassTypes(self):
        return presets.BASS_TYPES

    @Property("QVariantList", constant=True)
    def eqFreqs(self):
        return EQ_FREQS

    @Property("QVariantList", notify=sinksChanged)
    def sinks(self):
        return self._sinks

    @Property("QVariantList", notify=spectrumChanged)
    def spectrumIn(self):
        return self._spec_in

    @Property("QVariantList", notify=spectrumChanged)
    def spectrumOut(self):
        return self._spec_out

    @Property("QVariantMap", notify=metersChanged)
    def meters(self):
        return self._meters

    @Property("QVariantList", notify=curveChanged)
    def eqCurve(self):
        return self._curve
