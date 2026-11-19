"""Malformed correction-file regressions."""
from http.client import IncompleteRead
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


class FilterCapacityTests(unittest.TestCase):
    def test_ddc_import_respects_dsp_filter_capacity(self):
        filters = correction.parse_vdc("SR_48000:" + ",".join(["1,0,0,0,0"] * 25), 48000)
        self.assertEqual(len(filters), 24)

    def test_parametric_import_respects_dsp_filter_capacity(self):
        _, filters = correction.parse_parametric("Filter: ON PK Fc 1000 Hz Gain 3 dB Q 1\n" * 25)
        self.assertEqual(len(filters), 24)


if __name__ == "__main__":
    unittest.main()
