"""Offline update-controller tests with deferred worker completions and real Qt timers."""
import os
import sys
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from PySide6.QtCore import QCoreApplication, QThread, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from resona import __version__, updater
from resona.backend import Backend
from resona.updates import UpdateController


class UpdateControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QApplication([])

    def setUp(self):
        self.pending = []
        self.state = {}
        self.touch = Mock()
        self.processing = True
        self.visible = True
        self.release = dict(available=True, version="9.0.0", notes="Release notes", url="https://example.com/release")
        self.kind = patch.object(updater, "install_kind", return_value="user").start()
        self.addCleanup(patch.stopall)
        self.service = UpdateController(self.state, self.run_async, self.touch,
                                        lambda: self.processing, lambda: self.visible)
        self.addCleanup(self.service.close)
        self.changed = Mock()
        self.toasts = Mock()
        self.service.updateChanged.connect(self.changed)
        self.service.toast.connect(self.toasts)

    def run_async(self, work, done):
        self.pending.append((work, done))

    def complete(self, result):
        _, done = self.pending.pop(0)
        done(result)

    def available(self):
        self.service.checkUpdates()
        self.complete(dict(self.release))

    def test_manual_check_preserves_information_and_does_not_auto_install(self):
        self.service.checkUpdates()
        self.assertEqual(self.service.updateInfo["state"], "checking")
        self.assertIs(self.pending[0][0], updater.check)
        with patch("resona.updates.time.time", return_value=12345):
            self.complete(self.release)
        self.assertEqual(self.service.updateInfo, dict(
            state="available", message="Resona 9.0.0 is available", version="9.0.0",
            notes="Release notes", url=self.release["url"], current=__version__, kind="user",
            freq="weekly", auto=True, last=12345,
        ))
        self.assertEqual(self.pending, [])
        self.assertEqual(self.changed.call_count, 2)
        self.toasts.assert_not_called()
        self.touch.assert_called_once_with()

    def test_current_release_and_failed_check_preserve_retry_behavior(self):
        self.service.checkUpdates()
        self.complete(OSError("offline"))
        self.assertEqual(self.service.updateInfo["state"], "error")
        self.assertEqual(self.service.updateInfo["message"], "Could not reach GitHub. Check your connection")
        self.assertNotIn("update_last", self.state)
        self.touch.assert_not_called()
        self.service.checkUpdates()
        self.complete(dict(available=False, version=__version__))
        self.assertEqual(self.service.updateInfo["state"], "current")
        self.assertEqual(self.service.updateInfo["notes"], "")
        self.assertEqual(self.service.updateInfo["message"], f"You're on the latest version ({__version__})")

    def test_busy_states_reject_duplicate_checks_and_installs(self):
        self.service.installUpdate()
        self.assertEqual(self.pending, [])
        self.service.checkUpdates()
        self.service.checkUpdates()
        self.service.installUpdate()
        self.assertEqual(len(self.pending), 1)
        self.complete(self.release)
        self.service.installUpdate()
        self.service.checkUpdates()
        self.service.installUpdate()
        self.assertEqual(len(self.pending), 1)
        with patch.object(updater, "relaunch"), patch("resona.updates.QCoreApplication.quit"):
            self.complete("/unused/resona")
        self.service.checkUpdates()
        self.service.installUpdate()
        self.assertEqual(self.pending, [])

    def test_install_error_allows_retry_and_runs_installer_with_release_metadata(self):
        self.available()
        self.service.installUpdate()
        with patch.object(updater, "install", return_value="/unused/resona") as install:
            self.assertEqual(self.pending[0][0](), "/unused/resona")
            install.assert_called_once_with(self.release)
        self.complete(RuntimeError("build failed"))
        self.assertEqual(self.service.updateInfo["state"], "available")
        self.assertEqual(self.service.updateInfo["message"], "build failed")
        self.toasts.assert_called_once_with("Update failed: build failed")
        self.assertFalse(self.service._restart_timer.isActive())
        self.service.installUpdate()
        self.assertEqual(len(self.pending), 1)

    def test_automatic_install_requires_enabled_user_installation(self):
        for kind, enabled in (("user", True), ("user", False), ("source", True), ("system", True)):
            with self.subTest(kind=kind, enabled=enabled):
                self.kind.return_value = kind
                self.state["update_auto"] = enabled
                self.service._check_updates(manual=False)
                self.complete(self.release)
                if kind == "user" and enabled:
                    self.assertEqual(self.service.updateInfo["state"], "installing")
                    self.toasts.assert_called_with("Updating Resona to 9.0.0")
                    self.complete(RuntimeError("test failure"))
                else:
                    self.assertEqual(self.service.updateInfo["state"], "available")
                    self.assertEqual(self.pending, [])
                    self.toasts.assert_called_with("Resona 9.0.0 is available. Open Settings to update")

    def test_manual_restart_forces_busy_audio_and_respects_visibility(self):
        for visible in (False, True):
            with self.subTest(visible=visible):
                self.visible = visible
                self.service._upd["state"] = "idle"
                self.available()
                self.service.installUpdate()
                with patch.object(updater, "relaunch") as relaunch, \
                        patch("resona.updates.QCoreApplication.quit") as quit_app:
                    self.complete("/unused/resona")
                relaunch.assert_called_once_with("/unused/resona", hidden=not visible)
                quit_app.assert_called_once_with()
                self.assertFalse(self.service._restart_timer.isActive())

    def test_automatic_restart_waits_for_quiet_audio(self):
        self.available()
        self.service.installUpdate(automatic=True)
        with patch.object(updater, "relaunch") as relaunch, \
                patch("resona.updates.QCoreApplication.quit") as quit_app:
            self.complete("/unused/resona")
            self.assertTrue(self.service._restart_timer.isActive())
            self.service._restart_timer.timeout.emit()
            relaunch.assert_not_called()
            quit_app.assert_not_called()
            self.processing = False
            self.service._restart_timer.timeout.emit()
            relaunch.assert_called_once_with("/unused/resona", hidden=False)
            quit_app.assert_called_once_with()
        self.assertFalse(self.service._restart_timer.isActive())

    def test_schedule_respects_frequency_last_check_and_exact_boundary(self):
        now = 1000000
        for frequency, last, due in (
            ("manual", 0, False), ("weekly", now - 7 * 86400 + 1, False),
            ("weekly", now - 7 * 86400, True), ("monthly", now - 7 * 86400, False),
            ("monthly", now - 30 * 86400, True), ("unknown", 0, True), ("weekly", now + 1, False),
        ):
            with self.subTest(frequency=frequency, last=last):
                self.state.update(update_freq=frequency, update_last=last)
                with patch("resona.updates.time.time", return_value=now):
                    self.service._upd_timer.timeout.emit()
                self.assertEqual(bool(self.pending), due)
                if due:
                    self.complete(OSError("test offline"))

    def test_preferences_persist_notify_and_return_independent_info(self):
        self.service.setUpdateFreq("monthly")
        self.service.setUpdateFreq("invalid")
        self.service.setUpdateAuto(False)
        self.assertEqual(self.state, dict(update_freq="monthly", update_auto=False))
        self.assertEqual(self.touch.call_count, 2)
        self.assertEqual(self.changed.call_count, 2)
        info = self.service.updateInfo
        info["state"] = "corrupted"
        self.assertEqual(self.service.updateInfo["state"], "idle")

    def test_screenshot_suppresses_only_startup_check(self):
        with patch.dict(os.environ, RESONA_SCREENSHOT="1"):
            service = UpdateController({}, self.run_async, self.touch, lambda: False, lambda: True)
        try:
            self.assertFalse(service._startup_timer.isActive())
            self.assertTrue(service._upd_timer.isActive())
            self.assertEqual(service._upd_timer.interval(), 6 * 3600 * 1000)
            self.assertEqual(service._restart_timer.interval(), 15000)
        finally:
            service.close()

    def test_close_stops_all_timers_and_ignores_late_check_completion(self):
        self.service.checkUpdates()
        before = self.service.updateInfo
        changed = self.changed.call_count
        self.service.close()
        self.service.close()
        self.complete(self.release)
        self.service._startup_timer.timeout.emit()
        self.service._upd_timer.timeout.emit()
        self.service.checkUpdates()
        self.service.installUpdate()
        self.service.setUpdateFreq("monthly")
        self.service.setUpdateAuto(False)
        self.assertEqual(self.service.updateInfo, before)
        self.assertEqual(self.state, {})
        self.assertEqual(self.pending, [])
        self.assertEqual(self.changed.call_count, changed)
        self.touch.assert_not_called()
        self.toasts.assert_not_called()
        for timer in self.service.findChildren(QTimer):
            self.assertFalse(timer.isActive())

    def test_close_ignores_late_install_success_or_failure(self):
        for result in ("/unused/resona", RuntimeError("test failure")):
            service = UpdateController({}, self.run_async, self.touch, lambda: False, lambda: True)
            try:
                service.checkUpdates()
                self.complete(self.release)
                service.installUpdate()
                service.close()
                with patch.object(updater, "relaunch") as relaunch, \
                        patch("resona.updates.QCoreApplication.quit") as quit_app:
                    self.complete(result)
                    service._restart_timer.timeout.emit()
                relaunch.assert_not_called()
                quit_app.assert_not_called()
                self.assertFalse(service._restart_timer.isActive())
            finally:
                service.close()

    def test_real_backend_forwards_qml_api_signals_and_closes_service(self):
        with ExitStack() as stack:
            stack.enter_context(patch("resona.backend.SharedState"))
            stack.enter_context(patch("resona.backend.pipeline.Pipeline", return_value=Mock(target=None)))
            stack.enter_context(patch("resona.backend.QProcess"))
            stack.enter_context(patch.object(Backend, "_load", return_value={}))
            stack.enter_context(patch.object(Backend, "_async", side_effect=self.run_async))
            for name in ("_recompute_curve", "_push_correction", "_refresh_sinks", "refreshHardware",
                         "startEngine", "_scan_apps", "_save"):
                stack.enter_context(patch.object(Backend, name))
            backend = Backend()
            try:
                changed, toast = Mock(), Mock()
                backend.updateChanged.connect(changed)
                backend.toast.connect(toast)
                self.assertIs(backend._updates.parent(), backend)
                backend.checkUpdates()
                self.complete(self.release)
                self.assertEqual(backend.updateInfo["state"], "available")
                self.assertEqual(changed.call_count, 2)
                backend._updates.toast.emit("forwarded")
                toast.assert_called_once_with("forwarded")
                backend.setUpdateFreq("manual")
                backend.setUpdateAuto(False)
                self.assertEqual(backend.updateInfo["freq"], "manual")
                self.assertFalse(backend.updateInfo["auto"])
                backend.shutdown()
                self.assertTrue(backend._updates._closed)
                for timer in backend._updates.findChildren(QTimer):
                    self.assertFalse(timer.isActive())
            finally:
                backend.shutdown()

    def test_real_worker_delivers_on_gui_thread_and_late_result_is_ignored(self):
        from PySide6.QtCore import QObject

        # Use the existing backend dispatcher without starting audio or any backend timers.
        dispatcher = Backend.__new__(Backend)
        QObject.__init__(dispatcher)
        dispatcher._closing = False
        for closed in (False, True):
            entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
            threads = []
            state = {}
            service = UpdateController(state, dispatcher._async, self.touch, lambda: True, lambda: True)

            def work():
                threads.append(threading.get_ident())
                entered.set()
                if not release.wait(timeout=5):
                    raise TimeoutError("test worker did not receive release")
                return dict(self.release)

            def dispatch(callback, result):
                self.assertEqual(QThread.currentThread(), self.app.thread())
                callback(result)
                delivered.set()

            dispatcher._call.connect(dispatch)
            try:
                with patch.object(updater, "check", side_effect=work):
                    service.checkUpdates()
                    self.assertTrue(entered.wait(timeout=5))
                    if closed:
                        service.close()
                    release.set()
                    deadline = time.monotonic() + 5
                    while not delivered.is_set() and time.monotonic() < deadline:
                        QTest.qWait(5)
                self.assertTrue(delivered.is_set())
                self.assertNotEqual(threads[0], threading.get_ident())
                self.assertEqual(service.updateInfo["state"], "checking" if closed else "available")
                self.assertEqual("update_last" in state, not closed)
            finally:
                release.set()
                service.close()
                dispatcher._call.disconnect(dispatch)

    def test_authenticity_errors_are_not_reported_as_network_errors(self):
        self.service.checkUpdates()
        self.complete(RuntimeError("Release lacks attested update files"))
        self.assertEqual(self.service.updateInfo["state"], "error")
        self.assertEqual(self.service.updateInfo["message"], "Release lacks attested update files")


if __name__ == "__main__":
    unittest.main()
