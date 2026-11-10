"""Update scheduling and presentation, separate from the audio controller."""
from __future__ import annotations

import os
import time

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal

from . import __version__, updater


class UpdateController(QObject):
    updateChanged = Signal()
    toast = Signal(str)

    def __init__(self, state, run_async, touch, is_processing, is_visible, parent=None):
        super().__init__(parent)
        self._state = state
        self._async = run_async
        self._touch = touch
        self._is_processing = is_processing
        self._is_visible = is_visible
        self._closed = False
        self._upd = {"state": "idle", "message": "", "version": "", "notes": "", "url": ""}
        self._upd_info: dict = {}
        self._relaunch: str | None = None
        self._upd_timer = QTimer(self, interval=6 * 3600 * 1000, timeout=self._maybe_check_updates)
        self._upd_timer.start()
        self._restart_timer = QTimer(self, interval=15000, timeout=self._try_restart)
        self._startup_timer = QTimer(self, singleShot=True, interval=45000, timeout=self._maybe_check_updates)
        if not os.environ.get("RESONA_SCREENSHOT"):
            self._startup_timer.start()

    def close(self):
        self._closed = True
        for timer in (self._upd_timer, self._restart_timer, self._startup_timer):
            timer.stop()

    def _set_upd(self, **kw):
        self._upd.update(kw)
        self.updateChanged.emit()

    def _maybe_check_updates(self):
        days = updater.FREQ_DAYS.get(self._state.get("update_freq", "weekly"), 7)
        if days and time.time() - self._state.get("update_last", 0) >= days * 86400:
            self._check_updates(manual=False)

    def checkUpdates(self):
        self._check_updates(manual=True)

    def _check_updates(self, manual: bool):
        if self._closed or self._upd["state"] in ("checking", "installing", "restarting"):
            return
        self._set_upd(state="checking", message="Checking GitHub releases…")

        def done(res):
            if self._closed:
                return
            if isinstance(res, Exception):
                message = str(res) if isinstance(res, RuntimeError) else "Could not reach GitHub. Check your connection"
                self._set_upd(state="error", message=message)
                return
            self._state["update_last"] = time.time()
            self._touch()
            self._upd_info = res
            if not res["available"]:
                self._set_upd(state="current", version=res["version"], notes="",
                              message=f"You're on the latest version ({__version__})")
                return
            self._set_upd(state="available", version=res["version"], notes=res["notes"], url=res["url"],
                          message=f"Resona {res['version']} is available")
            kind = updater.install_kind()
            if not manual and self._state.get("update_auto", True) and kind == "user":
                self.toast.emit(f"Updating Resona to {res['version']}")
                self.installUpdate(automatic=True)
            elif not manual:
                self.toast.emit(f"Resona {res['version']} is available. Open Settings to update")
        self._async(updater.check, done)

    def installUpdate(self, automatic: bool = False):
        if self._closed or self._upd["state"] != "available" or not self._upd_info:
            return
        self._set_upd(state="installing", message=f"Downloading and building {self._upd_info['version']}…")

        def done(res):
            if self._closed:
                return
            if isinstance(res, Exception):
                self._set_upd(state="available", message=str(res))
                self.toast.emit(f"Update failed: {res}")
                return
            self._relaunch = res
            self._set_upd(state="restarting", message=f"Installed {self._upd_info['version']}. Restarting Resona…")
            self._restart_timer.start()
            self._try_restart(force=not automatic)
        self._async(lambda: updater.install(self._upd_info), done)

    def _try_restart(self, force: bool = False):
        # an automatic update waits for a quiet moment so music or a game is never cut off
        if self._closed or not self._relaunch or (not force and self._is_processing()):
            return
        self._restart_timer.stop()
        updater.relaunch(self._relaunch, hidden=not self._is_visible())
        QCoreApplication.quit()

    @property
    def updateInfo(self):
        return dict(self._upd, current=__version__, kind=updater.install_kind(),
                    freq=self._state.get("update_freq", "weekly"), auto=self._state.get("update_auto", True),
                    last=self._state.get("update_last", 0))

    def setUpdateFreq(self, freq: str):
        if not self._closed and freq in updater.FREQ_DAYS:
            self._state["update_freq"] = freq
            self._touch()
            self.updateChanged.emit()

    def setUpdateAuto(self, on: bool):
        if self._closed:
            return
        self._state["update_auto"] = bool(on)
        self._touch()
        self.updateChanged.emit()
