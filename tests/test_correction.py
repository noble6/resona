"""Malformed correction-file regressions."""
from http.client import IncompleteRead
import io
import os
import struct
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import correction, persistence


class AutoEqDownloadTests(unittest.TestCase):
    def download(self, body, length=None):
        response = io.BytesIO(body)
        response.headers = {} if length is None else {"Content-Length": length}
        with patch.object(correction.urllib.request, "urlopen", return_value=response), \
                patch.object(response, "read", wraps=response.read) as read, \
                patch.object(correction, "MAX_AUTOEQ_BYTES", 32):
            try:
                return correction._get("https://example.invalid/index")
            finally:
                self.assertTrue(response.closed)
                if read.called:
                    read.assert_called_once_with(33)

    def test_small_response_with_or_without_length(self):
        self.assertEqual(self.download(b"index"), "index")
        self.assertEqual(self.download(b"index", "5"), "index")

    def test_limit_is_inclusive(self):
        self.assertEqual(self.download(b"x" * 32, "32"), "x" * 32)

    def test_oversized_body_without_length_is_rejected(self):
        with self.assertRaises(OSError):
            self.download(b"x" * 33)

    def test_oversized_declared_length_is_rejected(self):
        with self.assertRaises(OSError):
            self.download(b"small", "33")

    def test_truncated_body_is_rejected(self):
        with self.assertRaises(OSError):
            self.download(b"partial", "20")

    def test_invalid_declared_lengths_are_rejected(self):
        for length in ("invalid", "-1"):
            with self.subTest(length=length), self.assertRaises(OSError):
                self.download(b"index", length)

    def test_invalid_utf8_keeps_existing_replacement_behavior(self):
        self.assertEqual(self.download(b"\xff"), "\ufffd")

    def test_rejected_responses_keep_valid_stale_cache(self):
        for body, length in ((b"x" * 33, None), (b"partial", "20")):
            with self.subTest(length=length), tempfile.TemporaryDirectory() as directory:
                cache = Path(directory) / "autoeq_index.md"
                old = "- [Old headphones](./old/path) by Old source\n"
                cache.write_text(old, encoding="utf-8")
                response = io.BytesIO(body)
                response.headers = {} if length is None else {"Content-Length": length}
                with patch.object(correction, "CACHE_DIR", Path(directory)), \
                        patch.object(correction, "MAX_AUTOEQ_BYTES", 32), \
                        patch.object(correction.urllib.request, "urlopen", return_value=response):
                    entries = correction.autoeq_index(max_age_days=0)
                self.assertEqual([entry["name"] for entry in entries], ["Old headphones"])
                self.assertEqual(cache.read_text(encoding="utf-8"), old)
                self.assertTrue(response.closed)


class AutoEqCacheTests(unittest.TestCase):
    OLD = "- [Old headphones](./old/path) by Old source\n"
    NEW = "- [New headphones](./new/path) by New source\n"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        directory = patch.object(correction, "CACHE_DIR", self.root / "cache")
        directory.start()
        self.addCleanup(directory.stop)
        self.cache = correction.CACHE_DIR / "autoeq_index.md"
        download = patch.object(correction, "_get", return_value=self.NEW)
        self.download = download.start()
        self.addCleanup(download.stop)

    def store(self, content, stale=False):
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        if stale:
            old = time.time() - 10 * 86400
            os.utime(self.cache, (old, old))

    def names(self, **kwargs):
        return [entry["name"] for entry in correction.autoeq_index(**kwargs)]

    def assert_no_temporary_files(self):
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_fresh_valid_cache_does_not_use_network(self):
        self.store(self.OLD)
        self.assertEqual(self.names(), ["Old headphones"])
        self.download.assert_not_called()

    def test_successful_refresh_replaces_stale_cache(self):
        self.store(self.OLD, stale=True)
        self.assertEqual(self.names(), ["New headphones"])
        self.assertEqual(self.cache.read_text(), self.NEW)
        self.assert_no_temporary_files()

    def test_unicode_names_and_source_metadata_survive_cache_round_trip(self):
        self.download.return_value = "- [Café headphones](./measured/model) by Test source on 2026-01-01\n"
        expected = [{"name": "Café headphones", "path": "measured/model", "source": "Test source · 2026-01-01"}]
        self.assertEqual(correction.autoeq_index(), expected)
        self.assertEqual(correction.autoeq_index(), expected)
        self.download.assert_called_once()

    def test_unusable_cache_directory_does_not_discard_a_download(self):
        correction.CACHE_DIR.write_text("not a directory")
        self.assertEqual(self.names(), ["New headphones"])
        self.assertEqual(correction.CACHE_DIR.read_text(), "not a directory")

    def test_cache_directory_error_keeps_download_and_old_cache(self):
        self.store(self.OLD, stale=True)
        mkdir = Path.mkdir

        def denied(path, *args, **kwargs):
            if path == correction.CACHE_DIR:
                raise PermissionError("cache is read-only")
            return mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", new=denied):
            self.assertEqual(self.names(), ["New headphones"])
        self.assertEqual(self.cache.read_text(), self.OLD)

    def test_unreadable_fresh_cache_still_tries_the_network(self):
        self.store(self.OLD)
        read = Path.read_text

        def denied(path, *args, **kwargs):
            if path == self.cache:
                raise PermissionError("cache is unreadable")
            return read(path, *args, **kwargs)

        with patch.object(Path, "read_text", new=denied):
            self.assertEqual(self.names(), ["New headphones"])
        self.download.assert_called_once()

    def test_invalid_utf8_cache_can_be_refreshed(self):
        self.store(b"\xff")
        self.assertEqual(self.names(), ["New headphones"])
        self.assertEqual(self.cache.read_text(), self.NEW)

    def test_network_failure_uses_valid_stale_cache(self):
        self.store(self.OLD, stale=True)
        self.download.side_effect = OSError("offline")
        self.assertEqual(self.names(), ["Old headphones"])
        self.assertEqual(self.cache.read_text(), self.OLD)

    def test_interrupted_response_uses_valid_stale_cache(self):
        self.store(self.OLD, stale=True)
        self.download.side_effect = IncompleteRead(b"partial", 100)
        self.assertEqual(self.names(), ["Old headphones"])
        self.assertEqual(self.cache.read_text(), self.OLD)

    def test_offline_with_missing_or_corrupt_cache_returns_no_results(self):
        self.download.side_effect = OSError("offline")
        self.assertEqual(self.names(), [])
        self.store(b"\xff")
        self.assertEqual(self.names(), [])

    def test_invalid_download_does_not_replace_valid_stale_cache(self):
        self.store(self.OLD, stale=True)
        for text in ("", "<html>unavailable</html>"):
            with self.subTest(text=text):
                self.download.return_value = text
                self.assertEqual(self.names(), ["Old headphones"])
                self.assertEqual(self.cache.read_text(), self.OLD)

    def test_fresh_but_invalid_index_is_not_reused(self):
        self.store("<html>not an index</html>")
        self.assertEqual(self.names(), ["New headphones"])
        self.assertEqual(self.cache.read_text(), self.NEW)

    def test_failed_replace_keeps_download_and_previous_cache(self):
        self.store(self.OLD, stale=True)
        with patch.object(persistence.os, "replace", side_effect=PermissionError("replace denied")):
            self.assertEqual(self.names(), ["New headphones"])
        self.assertEqual(self.cache.read_text(), self.OLD)
        self.assert_no_temporary_files()

    def test_partial_staged_write_cannot_damage_previous_cache(self):
        self.store(self.OLD, stale=True)
        create = persistence.tempfile.NamedTemporaryFile

        def failing_stream(*args, **kwargs):
            stream = create(*args, **kwargs)
            write = stream.write

            def partial_write(content):
                write(content[:10])
                raise OSError("disk full")

            stream.write = partial_write
            return stream

        with patch.object(persistence.tempfile, "NamedTemporaryFile", side_effect=failing_stream):
            self.assertEqual(self.names(), ["New headphones"])
        self.assertEqual(self.cache.read_text(), self.OLD)
        self.assert_no_temporary_files()

    def test_zero_max_age_forces_refresh(self):
        self.store(self.OLD)
        self.assertEqual(self.names(max_age_days=0), ["New headphones"])
        self.download.assert_called_once()


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

    def gain(self, samples):
        samples = np.asarray(samples, dtype="<f4")
        channels = samples.shape[1]
        fmt = struct.pack("<HHIIHH", 3, channels, 48000,
                          48000 * channels * 4, channels * 4, 32)
        return self.read(fmt, samples.tobytes())["gain"]

    def test_true_stereo_opposite_polarities_do_not_cancel_gain_estimate(self):
        self.assertEqual(self.gain([[1, 0, -1, 0], [0, 0, 0, 0]]), 0.5)

    def test_true_stereo_right_output_uses_both_input_paths(self):
        self.assertEqual(self.gain([[0, 1, 0, -1], [0, 0, 0, 0]]), 0.5)

    def test_true_stereo_delayed_paths_do_not_cancel_gain_estimate(self):
        self.assertEqual(self.gain([[1, 0, 0, 0], [0, 0, -1, 0]]), 0.5)

    def test_true_stereo_combines_magnitudes_at_each_frequency(self):
        gain = self.gain([[1, 0, 1, 0], [1, 0, -1, 0]])
        self.assertAlmostEqual(gain, 1 / (2 * np.sqrt(2)), places=12)

    def test_true_stereo_same_polarities_keep_existing_gain(self):
        self.assertEqual(self.gain([[1, 0, 1, 0], [0, 0, 0, 0]]), 0.5)

    def test_independent_stereo_channels_are_not_summed(self):
        self.assertEqual(self.gain([[1, -1], [0, 0]]), 1.0)

    def test_silent_true_stereo_has_unity_gain(self):
        self.assertEqual(self.gain(np.zeros((2, 4))), 1.0)

    def test_small_gain_does_not_round_to_silence(self):
        self.assertAlmostEqual(self.gain([[1e7], [0]]), 1e-7, delta=1e-15)

    def test_gain_rounding_does_not_raise_normalized_peak(self):
        gain = self.gain([[600000], [0]])
        self.assertLessEqual(gain * 600000, 1.00000001)
        self.assertGreater(gain, 0)


class ParametricNumberTests(unittest.TestCase):
    def test_explicit_plus_signs_are_preserved(self):
        preamp, filters = correction.parse_parametric(
            "Preamp: +3 dB\nFilter: ON PK Fc +1000 Hz Gain +6 dB Q +1")
        self.assertEqual(preamp, 3)
        self.assertEqual(filters, [dict(type="PK", freq=1000, gain=6, q=1)])

    def test_scientific_notation_is_not_truncated(self):
        preamp, filters = correction.parse_parametric(
            "Preamp: -3e0 dB\nFilter: ON PK Fc 1e3 Hz Gain 6e0 dB Q 1e1")
        self.assertEqual(preamp, -3)
        self.assertEqual(filters, [dict(type="PK", freq=1000, gain=6, q=10)])

    def test_decimal_forms_and_kilohertz_are_preserved(self):
        _, filters = correction.parse_parametric("Filter: ON PK Fc +1.5 kHz Gain -.5 dB Q .7")
        self.assertEqual(filters, [dict(type="PK", freq=1500, gain=-0.5, q=0.7)])

    def test_negative_q_is_not_replaced_with_default(self):
        _, filters = correction.parse_parametric("Filter: ON PK Fc 1000 Hz Gain 6 dB Q -1")
        self.assertEqual(filters[0]["q"], -1)

    def test_missing_optional_values_keep_defaults(self):
        _, filters = correction.parse_parametric("Filter: ON HP Fc 100 Hz")
        self.assertEqual(filters, [dict(type="HP", freq=100, gain=0, q=0.7071)])

    def test_malformed_q_is_not_replaced_with_default(self):
        for q in ("1e", "1e-", "nan", "1.2.3"):
            with self.subTest(q=q), self.assertRaises(ValueError):
                correction.parse_parametric(f"Filter: ON PK Fc 1000 Hz Gain 6 dB Q {q}")

    def test_q_can_be_followed_by_a_comment(self):
        _, filters = correction.parse_parametric("Filter: ON PK Fc 1000 Hz Gain 6 dB Q +1#comment")
        self.assertEqual(filters[0]["q"], 1)


class ParametricCommentTests(unittest.TestCase):
    def test_inline_comment_cannot_supply_optional_filter_values(self):
        _, filters = correction.parse_parametric(
            "Filter: ON HP Fc 100 Hz # Gain 12 dB Q 100")
        self.assertEqual(filters, [dict(type="HP", freq=100, gain=0, q=0.7071)])

    def test_inline_comment_cannot_supply_required_frequency(self):
        _, filters = correction.parse_parametric("Filter: ON PK # Fc 1000 Hz Gain 12 dB Q 1")
        self.assertEqual(filters, [])

    def test_invalid_q_in_comment_does_not_reject_a_valid_filter(self):
        _, filters = correction.parse_parametric("Filter: ON HP Fc 100 Hz # Q invalid")
        self.assertEqual(filters, [dict(type="HP", freq=100, gain=0, q=0.7071)])

    def test_comments_and_disabled_filters_do_not_change_values(self):
        preamp, filters = correction.parse_parametric(
            "# Preamp: 12 dB\nPreamp: -3 dB # Preamp: 6 dB\n"
            "Filter: OFF PK Fc 1000 Hz Gain 12 dB Q 1\n"
            "Filter: ON PK Fc 1000 Hz Gain +6 dB Q +1# Q 2")
        self.assertEqual(preamp, -3)
        self.assertEqual(filters, [dict(type="PK", freq=1000, gain=6, q=1)])


class FilterCapacityTests(unittest.TestCase):
    def test_ddc_import_respects_dsp_filter_capacity(self):
        filters = correction.parse_vdc("SR_48000:" + ",".join(["1,0,0,0,0"] * 25), 48000)
        self.assertEqual(len(filters), 24)

    def test_parametric_import_respects_dsp_filter_capacity(self):
        _, filters = correction.parse_parametric("Filter: ON PK Fc 1000 Hz Gain 3 dB Q 1\n" * 25)
        self.assertEqual(len(filters), 24)


if __name__ == "__main__":
    unittest.main()
