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


if __name__ == "__main__":
    unittest.main()
