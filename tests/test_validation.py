"""Saved state and imported presets are untrusted JSON, not controller objects."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import presets, validation


class ValidationTests(unittest.TestCase):
    def test_defaults_and_all_profiles_validate(self):
        self.assertEqual(validation.params(presets.DEFAULTS), presets.DEFAULTS)
        for name in presets.PROFILES:
            for device in presets.DEVICE_MODES:
                validation.state({"params": presets.profile_params(name, device)})

    def test_wrong_shapes_and_nonfinite_values_are_rejected(self):
        for data in ([], None, {"params": []}, {"params": {"eq0": "bad"}},
                     {"params": {"eq0": float("nan")}}, {"params": {"eq0": 100}},
                     {"device_memory": {"sink": []}}, {"app_rules": []},
                     {"correction": {"filters": [None]}}, {"ir": {"path": []}},
                     {"update_last": float("inf")}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                validation.state(data)

    def test_invalid_filter_values_are_rejected(self):
        for field in ("freq", "gain", "q"):
            section = {"type": "PK", "freq": 1000, "gain": 6, "q": 1, field: float("nan")}
            with self.assertRaises(ValueError):
                validation.correction({"filters": [section]})

    def test_unknown_params_are_ignored_for_forward_compatibility(self):
        self.assertEqual(validation.params({"future_param": 99, "eq0": 3}), {"eq0": 3})


if __name__ == "__main__":
    unittest.main()
