"""Persistence tests use temporary directories only; no Qt or audio server is needed."""
import json
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import persistence


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state = self.root / "config/state.json"
        self.presets = self.root / "config/presets"
        for name, value in (("STATE_FILE", self.state), ("PRESET_DIR", self.presets)):
            patcher = patch.object(persistence, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def assert_no_temporary_files(self):
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_state_round_trip_retains_settings_and_legacy_migration(self):
        saved = {"params": {"bass_amt": 0.8}, "profile": "Music", "update_freq": "monthly",
                 "correction": {"filters": [{"type": "PK", "freq": 1000, "gain": -30, "q": 1}]}}
        persistence.save_state(saved)
        loaded = persistence.load_state()
        self.assertEqual(loaded["params"]["bass_amt"], 0.8)
        self.assertEqual(loaded["profile"], "Music")
        self.assertEqual(loaded["update_freq"], "monthly")
        self.assertEqual(loaded["correction"]["filters"][0]["gain"], -24)
        self.assertEqual(saved["correction"]["filters"][0]["gain"], -30)
        self.assert_no_temporary_files()

    def test_missing_malformed_invalid_and_unreadable_state_fall_back(self):
        self.assertEqual(persistence.load_state(), {})
        self.state.parent.mkdir()
        for content in (b"broken", b"\xff", b"[]", b'{"params": {"bass_amt": 20}}'):
            self.state.write_bytes(content)
            self.assertEqual(persistence.load_state(), {})
        with patch.object(persistence, "read_json", side_effect=PermissionError("denied")):
            self.assertEqual(persistence.load_state(), {})

    def test_failed_replace_preserves_previous_file_and_cleans_workspace(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                if existing:
                    persistence.save_state({"params": {"bass_amt": 0.2}})
                before = self.state.read_bytes() if existing else None
                with patch.object(persistence.os, "replace", side_effect=PermissionError("denied")):
                    with self.assertRaises(PermissionError):
                        persistence.save_state({"params": {"bass_amt": 0.9}})
                self.assertEqual(self.state.read_bytes() if self.state.exists() else None, before)
                self.assert_no_temporary_files()

    def test_failed_flush_preserves_previous_file_and_cleans_workspace(self):
        persistence.save_state({"params": {"bass_amt": 0.2}})
        before = self.state.read_bytes()
        with patch.object(persistence.os, "fsync", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                persistence.save_state({"params": {"bass_amt": 0.9}})
        self.assertEqual(self.state.read_bytes(), before)
        self.assert_no_temporary_files()

    def test_serialization_failure_never_touches_existing_files(self):
        persistence.save_state({"params": {}})
        before = self.state.read_bytes()
        for value, error in ((object(), TypeError), (float("nan"), ValueError)):
            with self.subTest(value=value), self.assertRaises(error):
                persistence.save_state({"value": value})
            self.assertEqual(self.state.read_bytes(), before)
            self.assert_no_temporary_files()

    def test_unique_workspaces_do_not_touch_old_fixed_temporary_file(self):
        self.state.parent.mkdir()
        sentinel = self.state.with_suffix(".tmp")
        sentinel.write_text("unrelated")
        persistence.save_state({"params": {}})
        self.assertEqual(sentinel.read_text(), "unrelated")
        self.assertEqual(list(self.state.parent.glob(".*.tmp")), [])

    def test_preset_names_and_listing_keep_existing_conventions(self):
        self.assertEqual(persistence.user_presets(), [])
        for name in ("Zed", "Alpha", "écho"):
            persistence.write_json(persistence.preset_path(name), {"params": {}})
        self.assertEqual(persistence.user_presets(), ["Alpha", "Zed", "écho"])
        self.assertEqual(persistence.preset_path("../bad:name").name, "___bad_name.json")
        self.assertEqual(persistence.preset_path("  Music  ").name, "Music.json")
        persistence.delete_preset("Alpha")
        persistence.delete_preset("missing")
        self.assertNotIn("Alpha", persistence.user_presets())

    def test_import_validates_before_replacing_and_preserves_source_bytes(self):
        source = self.root / "imported.json"
        content = b'{ "params": {"bass_amt": 0.8}, "custom": "keep formatting" }\n'
        source.write_bytes(content)
        destination = persistence.preset_path("Imported")
        data = persistence.import_preset(source, destination)
        self.assertEqual(data["params"]["bass_amt"], 0.8)
        self.assertEqual(destination.read_bytes(), content)
        self.assertEqual(source.read_bytes(), content)
        for invalid in (b"[]", b"{}", b"broken", b'{"params":{"bass_amt":20}}'):
            source.write_bytes(invalid)
            with self.assertRaises(ValueError):
                persistence.import_preset(source, destination)
            self.assertEqual(destination.read_bytes(), content)
        self.assert_no_temporary_files()

    def test_import_and_export_can_use_the_same_file_without_truncation(self):
        source = persistence.preset_path("Same")
        persistence.write_json(source, {"params": {"bass_amt": 0.5}})
        before = source.read_bytes()
        persistence.import_preset(source, source)
        persistence.copy_file(source, source)
        self.assertEqual(source.read_bytes(), before)
        self.assert_no_temporary_files()

    def test_failed_export_keeps_existing_destination(self):
        source = persistence.preset_path("Source")
        persistence.write_json(source, {"params": {}})
        destination = self.root / "export.json"
        destination.write_text("old export")
        with patch.object(persistence.os, "replace", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                persistence.copy_file(source, destination)
        self.assertEqual(destination.read_text(), "old export")
        self.assert_no_temporary_files()

    def test_new_files_are_private(self):
        persistence.save_state({"params": {}})
        self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o600)

    def test_partial_write_failure_preserves_previous_file(self):
        persistence.save_state({"params": {"bass_amt": 0.2}})
        before = self.state.read_bytes()
        create = persistence.tempfile.NamedTemporaryFile

        def failing_stream(*args, **kwargs):
            stream = create(*args, **kwargs)
            write = stream.write

            def partial_write(content):
                write(content[:5])
                raise OSError("disk full during write")

            stream.write = partial_write
            return stream

        with patch.object(persistence.tempfile, "NamedTemporaryFile", side_effect=failing_stream):
            with self.assertRaises(OSError):
                persistence.save_state({"params": {"bass_amt": 0.9}})
        self.assertEqual(self.state.read_bytes(), before)
        self.assert_no_temporary_files()

    def test_concurrent_writers_publish_complete_json_without_colliding(self):
        values = [{"params": {"bass_amt": index / 100}} for index in range(16)]
        with ThreadPoolExecutor(max_workers=4) as workers:
            list(workers.map(persistence.save_state, values))
        self.assertIn(json.loads(self.state.read_bytes()), values)
        self.assert_no_temporary_files()


if __name__ == "__main__":
    unittest.main()
