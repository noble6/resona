"""Offline controller regressions; no audio server or GUI is started."""
import sys
import json
import tempfile
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona.backend import Backend


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
            with patch("resona.backend.STATE_FILE", path):
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
                _visuals=True, _processing=True, _set_upd=Mock(),
                _restart_timer=SimpleNamespace(start=Mock()), _try_restart=Mock(),
                _async=lambda work, done: done("/unused/resona"),
            )
            Backend.installUpdate(controller, automatic=automatic)
            controller._try_restart.assert_called_once_with(force=not automatic)


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
                    with patch("resona.backend.CONFIG_DIR", root), \
                            patch("resona.backend.STATE_FILE", root / "state.json"):
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


if __name__ == "__main__":
    unittest.main()
