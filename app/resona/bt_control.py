"""QML-facing controller for Bluetooth audio auto-connect (exposed as `audio.bt`)."""
from __future__ import annotations

import re
import time

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from . import bluetooth

ADDRESS = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")


def sanitize(cfg) -> dict:
    cfg = cfg if isinstance(cfg, dict) else {}
    skip = cfg.get("skip") if isinstance(cfg.get("skip"), dict) else {}
    return {"auto": cfg.get("auto") is True,
            "skip": {a: True for a, v in skip.items() if isinstance(a, str) and ADDRESS.match(a) and v is True}}


class BluetoothController(QObject):
    changed = Signal()
    toast = Signal(str)
    POLL_MS = 15000

    def __init__(self, state: dict, run_async, touch, parent=None):
        super().__init__(parent)
        self._cfg = sanitize(state.get("bt"))
        state["bt"] = self._cfg
        self._async = run_async
        self._touch = touch
        self._closing = False
        self._status = {"service": False, "error": "", "adapter": None, "devices": []}
        self._checked = False
        self._busy_paths: set[str] = set()
        self._polling = False
        self._powered = None
        self._policy = bluetooth.AutoConnect()
        self._timer = QTimer(self, interval=self.POLL_MS, timeout=self._poll)
        if self._cfg["auto"]:
            self._timer.start()

    def begin(self):
        self._poll()

    def close(self):
        self._closing = True
        self._timer.stop()

    def _poll(self):
        if self._closing or self._polling:
            return
        self._polling = True
        self._async(bluetooth.status, self._polled)

    def _polled(self, st):
        self._polling = False
        if self._closing:
            return
        if isinstance(st, Exception):
            st = {"service": False, "error": str(st), "adapter": None, "devices": []}
        powered = bool(st.get("adapter") and st["adapter"].get("powered"))
        if powered and self._powered is False:
            self._policy.reset()            # adapter just came back: try everyone now
        self._powered = powered
        self._status, self._checked = st, True
        self.changed.emit()
        if not (self._cfg["auto"] and powered):
            return
        skip = {a: False for a in self._cfg["skip"]}
        for d in self._policy.due(st["devices"], skip, time.monotonic()):
            self._dial(d, quiet=True)

    def _dial(self, d: dict, quiet: bool):
        path = d["path"]
        if path in self._busy_paths:
            return
        self._busy_paths.add(path)
        self.changed.emit()

        def done(res):
            self._busy_paths.discard(path)
            if self._closing:
                return
            ok, err = res if isinstance(res, tuple) else (False, str(res))
            self._policy.result(d["address"], ok, time.monotonic())
            if ok:
                self.toast.emit(f"Connected {d['name'] or d['address']}")
            elif not quiet:
                self.toast.emit(f"Could not connect {d['name'] or d['address']}: {err}")
            self._poll()
        self._async(lambda: bluetooth.connect(path), done)

    # ------------------------------------------------------------------ QML API
    @Property("QVariantMap", notify=changed)
    def info(self):
        devices = [dict(d, auto=d["address"] not in self._cfg["skip"], busy=d["path"] in self._busy_paths)
                   for d in self._status.get("devices", [])]
        return {"auto": self._cfg["auto"], "checked": self._checked, "service": self._status.get("service", False),
                "error": self._status.get("error", ""), "powered": bool(self._powered), "devices": devices}

    @Slot()
    def refresh(self):
        self._poll()

    @Slot(bool)
    def setAuto(self, on: bool):
        self._cfg["auto"] = bool(on)
        self._touch()
        if on:
            self._policy.reset()
            self._timer.start()
            self._poll()
        else:
            self._timer.stop()
        self.changed.emit()

    @Slot(str, bool)
    def setDeviceAuto(self, address: str, on: bool):
        if not ADDRESS.match(address or ""):
            return
        if on:
            self._cfg["skip"].pop(address, None)
            self._policy.reset()
        else:
            self._cfg["skip"][address] = True
        self._touch()
        self.changed.emit()

    @Slot(str)
    def connectDevice(self, path: str):
        for d in self._status.get("devices", []):
            if d["path"] == path:
                self._dial(d, quiet=False)

    @Slot(str)
    def disconnectDevice(self, path: str):
        def done(_):
            if not self._closing:
                self._poll()
        self._async(lambda: bluetooth.disconnect(path), done)
