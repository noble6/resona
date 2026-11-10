"""Offline controller regressions; no audio server or GUI is started."""
import sys
import json
import threading
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona.backend import Backend
from resona import persistence, presets
from resona.updates import UpdateController


class PresetTests(unittest.TestCase):
    def test_preset_keeps_correction_toggle_and_tuned_preamp(self):
        params = {}
        controller = SimpleNamespace(
            _state={}, _apply=params.update, _push_correction=Mock(), _touch=Mock(),
            stateChanged=SimpleNamespace(emit=Mock()), toast=SimpleNamespace(emit=Mock()),
        )
        controller._restore = MethodType(Backend._restore, controller)
        controller._set_correction = MethodType(Backend._set_correction, controller)
        data = {"params": {"corr_on": 0, "corr_preamp": -7},
                "correction": {"filters": [], "preamp": -3}}
        Backend._load_preset_data(controller, data, "disabled correction")
        self.assertEqual(params["corr_on"], 0)
        self.assertEqual(params["corr_preamp"], -7)

    def test_long_legacy_correction_does_not_discard_saved_settings(self):
        section = {"type": "RAW", "b0": 1, "b1": 0, "b2": 0, "a1": 0, "a2": 0}
        saved = {"params": {"bass_amt": 0.8}, "correction": {"filters": [section] * 25}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps(saved))
            with patch("resona.persistence.STATE_FILE", path):
                loaded = Backend._load(None)
        self.assertEqual(loaded["params"]["bass_amt"], 0.8)
        self.assertEqual(len(loaded["correction"]["filters"]), 24)

    def test_clean_preset_clears_previous_correction(self):
        for correction in (None, {}):
            controller = SimpleNamespace(
                _restore=Mock(), _set_correction=Mock(), clearCorrection=Mock(),
                toast=SimpleNamespace(emit=Mock()),
            )
            Backend._load_preset_data(controller, {"params": {}, "correction": correction}, "clean")
            controller.clearCorrection.assert_called_once_with()
            controller._set_correction.assert_not_called()

    def test_preset_with_correction_replaces_previous_correction(self):
        controller = SimpleNamespace(
            _restore=Mock(), _set_correction=Mock(), clearCorrection=Mock(),
            toast=SimpleNamespace(emit=Mock()),
        )
        correction = {"name": "test", "filters": []}
        Backend._load_preset_data(controller, {"params": {}, "correction": correction}, "test")
        controller._set_correction.assert_called_once_with(correction)
        controller.clearCorrection.assert_not_called()


class UpdateTests(unittest.TestCase):
    def test_only_manual_update_forces_restart(self):
        for automatic in (False, True):
            controller = SimpleNamespace(
                _upd={"state": "available"}, _upd_info={"version": "9.0"},
                _closed=False, _set_upd=Mock(),
                _restart_timer=SimpleNamespace(start=Mock()), _try_restart=Mock(),
                _async=lambda work, done: done("/unused/resona"),
            )
            UpdateController.installUpdate(controller, automatic=automatic)
            controller._try_restart.assert_called_once_with(force=not automatic)

    def test_backend_update_slots_delegate_without_changing_arguments(self):
        service = Mock()
        controller = SimpleNamespace(_updates=service)
        Backend.checkUpdates(controller)
        service.checkUpdates.assert_called_once_with()
        Backend.installUpdate(controller)
        Backend.installUpdate(controller, automatic=True)
        self.assertEqual(service.installUpdate.call_args_list, [unittest.mock.call(automatic=False),
                                                               unittest.mock.call(automatic=True)])
        Backend.setUpdateFreq(controller, "monthly")
        service.setUpdateFreq.assert_called_once_with("monthly")
        Backend.setUpdateAuto(controller, False)
        service.setUpdateAuto.assert_called_once_with(False)


class CorrectionTests(unittest.TestCase):
    def controller(self):
        from resona import presets

        params = dict(presets.DEFAULTS, bass_amt=0.8)
        controller = SimpleNamespace(
            _state={"profile": "Music"}, _params=params, _auto_base=None,
            _apply=params.update, _push_correction=Mock(), _touch=Mock(),
            shm=SimpleNamespace(sample_rate=48000), toast=SimpleNamespace(emit=Mock()),
        )
        controller._set_correction = MethodType(Backend._set_correction, controller)
        return controller

    def test_import_save_reload_normalizes_gain_without_losing_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for gain in (-30, 30):
                with self.subTest(gain=gain):
                    source = root / "correction.txt"
                    source.write_text(f"Filter: ON PK Fc 1000 Hz Gain {gain} dB Q 1")
                    controller = self.controller()
                    Backend.importCorrection(controller, str(source))
                    with patch("resona.persistence.STATE_FILE", root / "state.json"):
                        Backend._save(controller)
                        loaded = Backend._load(None)
                    self.assertEqual(loaded["profile"], "Music")
                    self.assertEqual(loaded["params"]["bass_amt"], 0.8)
                    self.assertEqual(loaded["correction"]["filters"][0]["gain"], max(-24, min(24, gain)))

    def test_legacy_gain_is_migrated_without_losing_settings(self):
        from resona import validation

        source = {"params": {"bass_amt": 0.8}, "correction": {
            "filters": [{"type": "PK", "freq": 1000, "gain": -30, "q": 1}]}}
        loaded = validation.state(source)
        self.assertEqual(loaded["params"]["bass_amt"], 0.8)
        self.assertEqual(loaded["correction"]["filters"][0]["gain"], -24)
        self.assertEqual(source["correction"]["filters"][0]["gain"], -30)

    def test_invalid_import_leaves_live_settings_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.txt"
            source.write_text("Filter: ON PK Fc 1000 Hz Gain 3 dB Q 0")
            controller = self.controller()
            previous = dict(controller._params)
            Backend.importCorrection(controller, str(source))
            self.assertNotIn("correction", controller._state)
            self.assertEqual(controller._params, previous)
            self.assertTrue(controller.toast.emit.call_args.args[0].startswith("Import failed:"))

    def test_ddc_is_bypassed_at_unsupported_rate_and_restored_at_supported_rate(self):
        controller = SimpleNamespace(
            _state={"correction": {"kind": "vdc", "text": "SR_48000:1,0,0,0,0", "filters": []}},
            _params={"corr_on": 1},
            shm=SimpleNamespace(sample_rate=96000, write_corr=Mock(), write=Mock()),
            toast=SimpleNamespace(emit=Mock()), correctionChanged=SimpleNamespace(emit=Mock()),
        )
        Backend._push_correction(controller)
        controller.shm.write_corr.assert_called_with([])
        controller.shm.write.assert_called_with({"corr_on": 0})
        controller.shm.sample_rate = 48000
        Backend._push_correction(controller)
        self.assertEqual(len(controller.shm.write_corr.call_args.args[0]), 1)
        controller.shm.write.assert_called_with({"corr_on": 1})


class AppearanceTests(unittest.TestCase):
    def test_reduced_motion_is_saved_and_notified(self):
        controller = SimpleNamespace(_state={}, stateChanged=SimpleNamespace(emit=Mock()), _touch=Mock())
        Backend.setReducedMotion(controller, True)
        self.assertTrue(controller._state["reduced_motion"])
        controller.stateChanged.emit.assert_called_once_with()
        controller._touch.assert_called_once_with()


class ShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict("os.environ", {"RESONA_SCREENSHOT": "unused"}))
        self.stack.enter_context(patch("resona.backend.SharedState"))
        self.pipe = Mock(target=None, wait_ready=Mock(return_value=False), last_log=Mock(return_value="stopped"))
        self.stack.enter_context(patch("resona.backend.pipeline.Pipeline", return_value=self.pipe))
        self.run = self.stack.enter_context(patch("resona.backend.pipeline._run", return_value="[]"))
        self.stack.enter_context(patch("resona.backend.QProcess"))
        self.stack.enter_context(patch.object(Backend, "_load", return_value={}))
        for name in ("_recompute_curve", "_push_correction", "_refresh_sinks", "refreshHardware", "_save"):
            self.stack.enter_context(patch.object(Backend, name))
        self.backend = Backend()
        self.addCleanup(self.backend.shutdown)

    def pump(self, milliseconds=30):
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    def test_shutdown_cancels_initial_start_and_delayed_app_scan(self):
        self.backend.shutdown()
        self.pump(1600)
        self.pipe.spawn.assert_not_called()
        self.run.assert_not_called()

    def test_late_start_results_do_not_revive_closed_backend(self):
        self.backend._busy = True
        self.backend._start_output_request = 0
        self.backend.shutdown()
        changed, toast = Mock(), Mock()
        self.backend.stateChanged.connect(changed)
        self.backend.toast.connect(toast)
        self.backend._device_switched = Mock()
        for success in (True, False):
            self.backend._startDone.emit(success, "late-device")
        self.assertFalse(self.backend.running)
        self.assertFalse(self.backend.busy)
        self.backend._device_switched.assert_not_called()
        changed.assert_not_called()
        toast.assert_not_called()
        self.assertFalse(self.backend._save_timer.isActive())
        self.assertFalse(self.backend._app_timer.isActive())

    def test_shutdown_is_idempotent(self):
        self.backend.shutdown()
        self.backend.shutdown()
        self.pipe.stop.assert_called_once_with(restore_default=True)
        self.backend.shm.close.assert_called_once_with()

    def test_inflight_readiness_cannot_revive_backend_after_shutdown(self):
        entered, release, delivered = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def wait_ready(**kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("readiness worker was not released")
            return True

        self.pipe.wait_ready.side_effect = wait_ready
        self.backend._startDone.connect(lambda success, target: delivered.set())
        self.backend.startEngine()
        self.assertTrue(entered.wait(5))
        self.backend.shutdown()
        release.set()
        for _ in range(100):
            self.pump(10)
            if delivered.is_set():
                break
        self.assertTrue(delivered.is_set())
        self.assertFalse(self.backend.running)
        self.assertFalse(self.backend.busy)
        self.pipe.spawn.assert_called_once()
        self.pipe.stop.assert_called_once_with(restore_default=True)
        self.assertFalse(self.backend._app_timer.isActive())

    def test_open_backend_delivers_worker_result_on_gui_thread(self):
        # Do not let the unrelated initial startup run while testing dispatch.
        self.backend._busy = True
        results, threads = [], []

        def done(result):
            results.append(result)
            threads.append(QThread.currentThread())

        self.backend._async(lambda: "result", done)
        for _ in range(100):
            self.pump(10)
            if results:
                break
        self.assertEqual(results, ["result"])
        self.assertEqual(threads, [self.app.thread()])

    def test_late_pactl_event_does_not_rearm_timers(self):
        self.backend.shutdown()
        self.backend._sub.readAllStandardOutput.return_value = b"Event 'new' on sink #1\n"
        self.backend._on_pactl_event()
        self.backend._sub.readAllStandardOutput.assert_not_called()
        for timer in (self.backend._evt_timer, self.backend._hw_timer, self.backend._vol_timer):
            self.assertFalse(timer.isActive())

    def test_worker_result_after_shutdown_is_not_delivered(self):
        entered, release, emitted = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        done = Mock()

        def work():
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test worker was not released")
            return "late-result"

        self.backend._call.connect(lambda callback, result: emitted.set())
        self.backend._async(work, done)
        self.assertTrue(entered.wait(5))
        self.backend.shutdown()
        release.set()
        for _ in range(100):
            self.pump(10)
            if emitted.is_set():
                break
        self.assertTrue(emitted.is_set())
        done.assert_not_called()

    def test_closed_backend_does_not_schedule_new_workers(self):
        self.backend.shutdown()
        with patch("resona.backend.threading.Thread") as worker:
            self.backend._async(Mock(), Mock())
        worker.assert_not_called()


class StartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        ShutdownTests.setUp(self)
        self.backend._anim.stop()
        self.stack.enter_context(patch.object(self.backend, "_pick_target", return_value="physical"))
        self.backend._device_switched = Mock()
        self.backend._state["output"] = "physical"
        self.pipe.target = "physical"

    pump = ShutdownTests.pump

    def settle(self):
        for _ in range(100):
            self.pump(10)
            if self.pipe.spawn.called and not self.backend.busy:
                break
        self.assertFalse(self.backend.busy, "startup did not leave the busy state")

    def test_readiness_failure_stops_child_and_keeps_output_choice(self):
        self.settle()
        self.assertFalse(self.backend.running)
        self.pipe.stop.assert_called_once_with(restore_default=True)
        self.assertEqual(self.backend._state["output"], "physical")
        self.assertNotIn("last_target", self.backend._state)
        self.assertEqual(self.backend.status, "Engine failed to start: stopped")

    def test_readiness_exception_reports_failure(self):
        self.pipe.wait_ready.side_effect = OSError("readiness failed")
        with patch("threading.excepthook") as unhandled:
            self.settle()
        unhandled.assert_not_called()
        self.assertFalse(self.backend.running)
        self.pipe.stop.assert_called_once_with(restore_default=True)
        self.assertEqual(self.backend.status, "Engine failed to start: readiness failed")

    def test_worker_launch_failure_stops_spawned_child(self):
        with patch("resona.backend.threading.Thread") as worker:
            worker.return_value.start.side_effect = RuntimeError("worker launch failed")
            self.settle()
        self.assertFalse(self.backend.running)
        self.pipe.stop.assert_called_once_with(restore_default=True)
        self.assertEqual(self.backend.status, "Engine failed to start: worker launch failed")

    def test_spawn_error_is_not_hidden_by_an_old_log(self):
        self.pipe.spawn.side_effect = OSError("launch failed")
        with patch("resona.backend.threading.Thread") as worker:
            self.settle()
        worker.assert_not_called()
        self.assertEqual(self.backend.status, "Engine failed to start: launch failed")

    def test_failed_output_can_be_selected_again_to_retry(self):
        self.settle()
        self.pipe.wait_ready.return_value = True
        self.backend.setOutput("physical")
        self.settle()
        self.assertEqual(self.pipe.spawn.call_count, 2)
        self.assertTrue(self.backend.running)
        self.assertEqual(self.backend._status, "Ready")
        self.assertEqual(self.backend._state["output"], "physical")


class OutputRequestTests(unittest.TestCase):
    def test_busy_start_keeps_the_inflight_generation(self):
        controller = SimpleNamespace(_closing=False, _busy=True, _output_request=2, _start_output_request=1,
                                     _ir_timer=SimpleNamespace(start=Mock()))
        Backend.startEngine(controller)
        self.assertEqual(controller._start_output_request, 1)
        controller._ir_timer.start.assert_called_once_with()

    def controller(self, requested, started):
        return SimpleNamespace(
            _closing=False,
            _state={"output": requested, "last_target": "previous"},
            _start_output_request=1, _output_request=1 if requested == started else 2,
            _device_switched=Mock(), _touch=Mock(), _sync_volume=Mock(),
            _app_timer=SimpleNamespace(start=Mock()), stateChanged=SimpleNamespace(emit=Mock()),
        )

    def test_completed_start_does_not_overwrite_a_newer_output_request(self):
        controller = self.controller("latest-choice", "starting-choice")
        Backend._on_started(controller, True, "starting-choice")
        self.assertEqual(controller._state["output"], "latest-choice")
        self.assertEqual(controller._state["last_target"], "starting-choice")
        controller._device_switched.assert_called_once_with("previous", "starting-choice")

    def test_normal_start_updates_output_to_selected_fallback(self):
        controller = self.controller("missing-device", "missing-device")
        Backend._on_started(controller, True, "fallback-device")
        self.assertEqual(controller._state["output"], "fallback-device")

    def test_returning_output_request_is_not_replaced_by_inflight_fallback(self):
        controller = self.controller("returning-device", "returning-device")
        controller._start_output_request = 1
        controller._output_request = 2
        Backend._on_started(controller, True, "temporary-fallback")
        self.assertEqual(controller._state["output"], "returning-device")

    def test_reselecting_inflight_target_cancels_another_pending_choice(self):
        controller = SimpleNamespace(_state={"output": "queued-choice"},
                                     _output_request=1, pipe=SimpleNamespace(target="starting-choice"), startEngine=Mock())
        Backend.setOutput(controller, "starting-choice")
        self.assertEqual(controller._state["output"], "starting-choice")
        self.assertEqual(controller._output_request, 2)
        controller.startEngine.assert_called_once_with()

    def test_reselecting_unchanged_output_does_not_restart(self):
        controller = SimpleNamespace(_state={"output": "same"}, _output_request=1,
                                     _running=True, _busy=False,
                                     pipe=SimpleNamespace(target="same"), startEngine=Mock())
        Backend.setOutput(controller, "same")
        controller.startEngine.assert_not_called()
        self.assertEqual(controller._output_request, 1)

    def test_reselecting_inflight_output_does_not_queue_another_start(self):
        controller = SimpleNamespace(_state={"output": "same"}, _output_request=1,
                                     _running=False, _busy=True,
                                     pipe=SimpleNamespace(target="same"), startEngine=Mock())
        Backend.setOutput(controller, "same")
        controller.startEngine.assert_not_called()
        self.assertEqual(controller._output_request, 1)


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state_file = self.root / "state.json"
        self.preset_dir = self.root / "presets"
        for name, value in (("STATE_FILE", self.state_file), ("PRESET_DIR", self.preset_dir)):
            patcher = patch.object(persistence, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.params = dict(presets.DEFAULTS, bass_amt=0.4, sysvol_db=-6, layout=2)
        self.controller = SimpleNamespace(
            _state={"profile": "Music"}, _params=self.params, _auto_base=None,
            profile="Music", deviceMode="headphones", modified=True, eqPreset="Flat",
            _apply=self.params.update, _set_correction=Mock(), clearCorrection=Mock(),
            stateChanged=SimpleNamespace(emit=Mock()), presetsChanged=SimpleNamespace(emit=Mock()),
            toast=SimpleNamespace(emit=Mock()),
        )
        for name in ("_snapshot", "_restore", "_preset_path", "_load_preset_data"):
            setattr(self.controller, name, MethodType(getattr(Backend, name), self.controller))

    def test_state_save_excludes_transient_controls_and_reloads(self):
        Backend._save(self.controller)
        saved = persistence.load_state()
        self.assertEqual(saved["profile"], "Music")
        self.assertEqual(saved["params"]["bass_amt"], 0.4)
        self.assertNotIn("sysvol_db", saved["params"])
        self.assertNotIn("layout", saved["params"])

    def test_state_save_uses_base_sound_during_temporary_app_profile(self):
        self.controller._auto_base = {"params": {"bass_amt": 0.2}}
        self.params["bass_amt"] = 0.9
        Backend._save(self.controller)
        self.assertEqual(persistence.load_state()["params"], {"bass_amt": 0.2})
        self.assertEqual(self.params["bass_amt"], 0.9)

    def test_state_save_failure_logs_without_damaging_previous_state(self):
        Backend._save(self.controller)
        before = self.state_file.read_bytes()
        self.params["bass_amt"] = 0.9
        with patch.object(persistence.os, "replace", side_effect=PermissionError("denied")), \
                patch("resona.backend.print") as log:
            Backend._save(self.controller)
        self.assertEqual(self.state_file.read_bytes(), before)
        self.assertEqual(log.call_args.args[0], "resona: could not save state:")
        self.assertEqual(list(self.root.rglob("*.tmp")), [])
        self.controller._state["invalid"] = object()
        with patch("resona.backend.print") as log:
            Backend._save(self.controller)
        log.assert_called_once()
        self.assertEqual(self.state_file.read_bytes(), before)

    def test_preset_save_and_load_preserve_sound_and_correction(self):
        correction = {"filters": [{"type": "PK", "freq": 1000, "gain": 3, "q": 1}]}
        self.controller._state["correction"] = correction
        Backend.savePreset(self.controller, "Saved")
        saved = persistence.read_json(persistence.preset_path("Saved"))
        self.assertEqual(saved["resona_preset"], 1)
        self.assertEqual(saved["correction"], correction)
        self.controller.presetsChanged.emit.assert_called_once_with()
        self.controller.toast.emit.assert_called_with("Saved “Saved”")
        self.params["bass_amt"] = 0.1
        Backend.loadPreset(self.controller, "Saved")
        self.assertEqual(self.params["bass_amt"], 0.4)
        self.controller._set_correction.assert_called_once_with(correction)
        self.controller.toast.emit.assert_called_with("Loaded “Saved”")

    def test_failed_preset_save_reports_error_without_success_signal(self):
        destination = persistence.preset_path("Saved")
        persistence.write_json(destination, {"params": {"bass_amt": 0.2}})
        before = destination.read_bytes()
        with patch.object(persistence.os, "fsync", side_effect=OSError("disk full")):
            Backend.savePreset(self.controller, "Saved")
        self.assertEqual(destination.read_bytes(), before)
        self.controller.presetsChanged.emit.assert_not_called()
        self.controller.toast.emit.assert_called_once_with("Preset: disk full")
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_blank_preset_name_is_a_no_op(self):
        Backend.savePreset(self.controller, "  ")
        self.assertFalse(self.preset_dir.exists())
        self.controller.presetsChanged.emit.assert_not_called()
        self.controller.toast.emit.assert_not_called()

    def test_failed_import_does_not_change_live_audio_or_existing_preset(self):
        source = self.root / "Imported.json"
        source.write_text(json.dumps({"params": {"bass_amt": 0.8}}))
        destination = persistence.preset_path(source.stem)
        persistence.write_json(destination, {"params": {"bass_amt": 0.2}})
        before = destination.read_bytes()
        previous_params = dict(self.params)
        previous_state = dict(self.controller._state)
        with patch.object(persistence.os, "replace", side_effect=PermissionError("denied")):
            Backend.importPreset(self.controller, str(source))
        self.assertEqual(self.params, previous_params)
        self.assertEqual(self.controller._state, previous_state)
        self.assertEqual(destination.read_bytes(), before)
        self.controller._set_correction.assert_not_called()
        self.controller.clearCorrection.assert_not_called()
        self.controller.presetsChanged.emit.assert_not_called()
        self.controller.toast.emit.assert_called_once_with("Import failed: denied")

    def test_successful_import_preserves_raw_file_and_applies_validated_sound(self):
        source = self.root / "Imported.json"
        content = b'{ "params": {"bass_amt": 0.8}, "correction": {"filters": [{"type":"PK", "freq":1000, "gain":-30, "q":1}]} }\n'
        source.write_bytes(content)
        Backend.importPreset(self.controller, source.as_uri())
        self.assertEqual(persistence.preset_path(source.stem).read_bytes(), content)
        self.assertEqual(self.params["bass_amt"], 0.8)
        self.assertEqual(self.controller._set_correction.call_args.args[0]["filters"][0]["gain"], -24)
        self.controller.presetsChanged.emit.assert_called_once_with()
        self.controller.toast.emit.assert_called_once_with("Loaded “Imported”")

    def test_export_extension_listing_and_delete_keep_existing_ui_contract(self):
        Backend.savePreset(self.controller, "Saved")
        self.assertEqual(Backend.userPresets.fget(self.controller), ["Saved"])
        Backend.exportPreset(self.controller, "Saved", str(self.root / "Export.txt"))
        self.assertEqual((self.root / "Export.json").read_bytes(), persistence.preset_path("Saved").read_bytes())
        self.assertFalse((self.root / "Export.txt").exists())
        self.controller.toast.emit.assert_called_with("Exported to Export.json")
        Backend.deletePreset(self.controller, "Saved")
        self.assertEqual(Backend.userPresets.fget(self.controller), [])


if __name__ == "__main__":
    unittest.main()
