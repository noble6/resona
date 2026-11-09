"""Offline controller regressions; no audio server or GUI is started."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona.backend import Backend


class PresetTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
