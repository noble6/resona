"""Pure correction preparation tests; no GUI, network, or audio server."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import correction, correction_model


class CorrectionModelTests(unittest.TestCase):
    def test_empty_correction_produces_zero_curve_and_keeps_toggle(self):
        for info in (None, {}):
            for enabled in (0, 1):
                result = correction_model.prepare(info, 48000, np.geomspace(20, 20000, 16), enabled)
                self.assertEqual(result.filters, [])
                self.assertEqual(result.curve, [0.0] * 16)
                self.assertEqual(result.enabled, enabled)
                self.assertEqual(result.warning, "")

    def test_parametric_curve_matches_existing_math_without_mutating_settings(self):
        info = dict(filters=[dict(type="PK", freq=1000, gain=6, q=1)], preamp=-4)
        previous = copy.deepcopy(info)
        frequencies = np.geomspace(20, 20000, 160)
        for rate in (44100, 48000, 96000, 192000):
            result = correction_model.prepare(info, rate, frequencies, 0)
            expected = correction.response_db(info["filters"], frequencies, rate, -4).round(2).tolist()
            self.assertEqual(result.curve, expected)
            self.assertEqual(result.filters, info["filters"])
            self.assertEqual(result.enabled, 0)
            self.assertEqual(info, previous)

    def test_ddc_bypass_is_temporary_and_supported_rate_restores_filters(self):
        info = dict(kind="vdc", text="SR_48000:1,0,0,0,0", filters=[], preamp=0)
        previous = copy.deepcopy(info)
        frequencies = np.geomspace(20, 20000, 16)
        bypass = correction_model.prepare(info, 96000, frequencies, 1)
        self.assertEqual(bypass.filters, [])
        self.assertEqual(bypass.enabled, 0)
        self.assertTrue(bypass.warning.endswith("; correction bypassed"))
        restored = correction_model.prepare(info, 48000, frequencies, 1)
        self.assertEqual(len(restored.filters), 1)
        self.assertEqual(restored.enabled, 1)
        self.assertEqual(restored.warning, "")
        self.assertEqual(info, previous)

    def test_import_parametric_and_ddc_files_keep_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, text, kind in (("Parametric.txt", "Preamp: -3 dB\nFilter: ON PK Fc 1000 Hz Gain 6 dB Q 1", "parametric"),
                                     ("Headphone.vdc", "SR_48000:1,0,0,0,0", "vdc")):
                path = root / name
                path.write_text(text)
                info = correction_model.from_file(path, 48000)
                self.assertEqual(info["name"], path.stem)
                self.assertEqual(info["kind"], kind)
                self.assertEqual(len(info["filters"]), 1)

    def test_invalid_import_and_unsupported_ddc_rate_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.txt"
            for text in ("not an EQ", "Filter: ON PK Fc 1000 Hz Gain 6 dB Q 0", "SR_48000:1,0,0,0,0"):
                path.write_text(text)
                with self.assertRaises(ValueError):
                    correction_model.from_file(path, 96000)

    def test_description_keeps_qml_field_names_and_count_fallback(self):
        self.assertEqual(correction_model.describe(None), dict(name="", source="", kind="", count=0, preamp=0))
        self.assertEqual(correction_model.describe(dict(name="DDC", count=4))["count"], 4)
        self.assertEqual(correction_model.describe(dict(filters=[{}], count=4))["count"], 1)


if __name__ == "__main__":
    unittest.main()
