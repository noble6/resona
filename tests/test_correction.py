"""Malformed correction-file regressions."""
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import correction


class ImpulseTests(unittest.TestCase):
    def read(self, fmt, data=b"\0" * 8):
        chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
        chunks += b"data" + struct.pack("<I", len(data)) + data
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.wav"
            path.write_bytes(b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks)
            return correction.read_ir(str(path))

    def test_short_format_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.read(b"\0")

    def test_zero_sample_rate_is_rejected(self):
        with self.assertRaises(ValueError):
            self.read(struct.pack("<HHIIHH", 1, 1, 0, 0, 2, 16))

    def test_incomplete_sample_is_rejected(self):
        with self.assertRaises(ValueError):
            self.read(struct.pack("<HHIIHH", 1, 2, 48000, 192000, 4, 16), b"\0" * 7)

    def test_nonfinite_float_samples_are_rejected(self):
        for value in (float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.read(struct.pack("<HHIIHH", 3, 1, 48000, 192000, 4, 32),
                          np.array([value, 0], dtype="<f4").tobytes())


class FilterCapacityTests(unittest.TestCase):
    def test_ddc_import_respects_dsp_filter_capacity(self):
        filters = correction.parse_vdc("SR_48000:" + ",".join(["1,0,0,0,0"] * 25), 48000)
        self.assertEqual(len(filters), 24)

    def test_parametric_import_respects_dsp_filter_capacity(self):
        _, filters = correction.parse_parametric("Filter: ON PK Fc 1000 Hz Gain 3 dB Q 1\n" * 25)
        self.assertEqual(len(filters), 24)


if __name__ == "__main__":
    unittest.main()
