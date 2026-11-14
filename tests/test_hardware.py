"""Hardware setting failures use temporary configuration files and mocked commands."""
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import hardware, persistence


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.hires = self.root / "pipewire.conf.d/hires.conf"
        self.configs = [self.root / "pulse.conf.d/resample.conf", self.root / "client.conf.d/resample.conf"]
        for name, value in (("HIRES_CONF", self.hires), ("RESAMPLE_CONFS", self.configs)):
            patcher = patch.object(hardware, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        commands = patch.object(hardware, "_run", return_value="")
        commands.start()
        self.addCleanup(commands.stop)
        checked = patch.object(hardware, "_command", return_value=True, create=True)
        self.commands = checked.start()
        self.addCleanup(checked.stop)

    def save(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def assert_no_staging(self):
        self.assertEqual(list(self.root.rglob(".resona-config-*")), [])
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_hires_round_trip_keeps_the_config_format(self):
        rates = hardware.set_hires(True, 96000)
        self.assertEqual(rates, [44100, 48000, 88200, 96000])
        self.assertIn("default.clock.allowed-rates = [ 44100 48000 88200 96000 ]", self.hires.read_text())
        self.assertTrue(hardware.hires_enabled())
        self.assertEqual(hardware.set_hires(False), [])
        self.assertFalse(self.hires.exists())
        self.assert_no_staging()

    def test_partial_staged_write_cannot_truncate_hires_config(self):
        self.save(self.hires, b"previous configuration\n")
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
            with self.assertRaises(OSError):
                hardware.set_hires(True)
        self.assertEqual(self.hires.read_bytes(), b"previous configuration\n")
        self.commands.assert_not_called()
        self.assert_no_staging()

    def test_failed_live_hires_change_restores_saved_settings(self):
        for on in (False, True):
            for existing in (False, True):
                with self.subTest(on=on, existing=existing):
                    if existing:
                        self.save(self.hires, b"old rates\n")
                    else:
                        self.hires.unlink(missing_ok=True)
                    self.commands.return_value = False
                    with self.assertRaisesRegex(RuntimeError, "Hi-Res"):
                        hardware.set_hires(on)
                    self.assertEqual(self.hires.read_bytes() if self.hires.exists() else None,
                                     b"old rates\n" if existing else None)
                    self.assert_no_staging()

    def test_live_hires_command_keeps_existing_arguments(self):
        hardware.set_hires(True, 48000)
        self.commands.assert_called_once_with("pw-metadata", "-n", "settings", "0",
                                               "clock.allowed-rates", "[ 44100 48000 ]")

    def test_disabling_hires_sets_a_safe_default_rate(self):
        hardware.set_hires(False)
        self.commands.assert_called_once_with("pw-metadata", "-n", "settings", "0", "clock.allowed-rates", "[ 48000 ]")

    def test_resampler_round_trip_updates_both_files(self):
        hardware.set_hq_resampler(True)
        self.assertTrue(hardware.hq_resampler_enabled())
        self.assertTrue(all("resample.quality = 14" in path.read_text() for path in self.configs))
        hardware.set_hq_resampler(False)
        self.assertFalse(hardware.hq_resampler_enabled())
        self.assertFalse(any(path.exists() for path in self.configs))
        self.assert_no_staging()

    def test_partial_legacy_resampler_config_is_not_reported_enabled(self):
        self.save(self.configs[0], b"resample.quality = 14\n")
        self.assertFalse(hardware.hq_resampler_enabled())

    def test_second_publish_failure_restores_old_or_missing_first_file(self):
        replace = os.replace
        for existing in (False, True):
            with self.subTest(existing=existing):
                first, second = self.configs
                if existing:
                    self.save(first, b"old first\n")
                    first.chmod(0o640)
                self.save(second, b"old second\n")

                def fail_second(source, destination):
                    if Path(destination) == second:
                        raise PermissionError("second publish failed")
                    return replace(source, destination)

                with patch.object(hardware.os, "replace", side_effect=fail_second):
                    with self.assertRaises(OSError):
                        hardware.set_hq_resampler(True)
                self.assertEqual(first.read_bytes() if first.exists() else None, b"old first\n" if existing else None)
                if existing:
                    self.assertEqual(first.stat().st_mode & 0o777, 0o640)
                self.assertEqual(second.read_bytes(), b"old second\n")
                self.assert_no_staging()

    def test_staging_failure_does_not_publish_either_file(self):
        first, second = self.configs
        self.save(first, b"old first\n")
        self.save(second, b"old second\n")
        copy = hardware.shutil.copy2

        def fail_second(source, destination, **kwargs):
            if source == second:
                raise PermissionError("second backup failed")
            return copy(source, destination, **kwargs)

        with patch.object(hardware.shutil, "copy2", side_effect=fail_second):
            with self.assertRaises(OSError):
                hardware.set_hq_resampler(True)
        self.assertEqual(first.read_bytes(), b"old first\n")
        self.assertEqual(second.read_bytes(), b"old second\n")
        self.assert_no_staging()

    def test_rollback_preserves_an_original_relative_symlink(self):
        first, second = self.configs
        self.save(first.parent / "original.conf", b"original target\n")
        first.symlink_to("original.conf")
        self.save(second, b"old second\n")
        replace = os.replace

        def fail_second(source, destination):
            if Path(destination) == second:
                raise PermissionError("second publish failed")
            return replace(source, destination)

        with patch.object(hardware.os, "replace", side_effect=fail_second):
            with self.assertRaises(OSError):
                hardware.set_hq_resampler(True)
        self.assertTrue(first.is_symlink())
        self.assertEqual(first.readlink(), Path("original.conf"))
        self.assertEqual(first.read_bytes(), b"original target\n")
        self.assert_no_staging()

    def test_second_delete_failure_restores_first_file(self):
        first, second = self.configs
        self.save(first, b"old first\n")
        self.save(second, b"old second\n")
        unlink = Path.unlink

        def fail_second(path, *args, **kwargs):
            if path == second:
                raise PermissionError("second delete failed")
            return unlink(path, *args, **kwargs)

        with patch.object(Path, "unlink", new=fail_second):
            with self.assertRaises(OSError):
                hardware.set_hq_resampler(False)
        self.assertEqual(first.read_bytes(), b"old first\n")
        self.assertEqual(second.read_bytes(), b"old second\n")
        self.assert_no_staging()

    def test_failed_rollback_keeps_backups_for_recovery(self):
        first, second = self.configs
        self.save(first, b"old first\n")
        self.save(second, b"old second\n")
        replace = os.replace

        def fail_publish_and_restore(source, destination):
            if Path(destination) == second or (Path(destination) == first and Path(source).name == "old"):
                raise PermissionError("injected publish/restore failure")
            return replace(source, destination)

        with patch.object(hardware.os, "replace", side_effect=fail_publish_and_restore):
            with self.assertRaisesRegex(OSError, "backups"):
                hardware.set_hq_resampler(True)
        backups = list(self.root.rglob(".resona-config-*/old"))
        self.assertTrue(any(path.read_bytes() == b"old first\n" for path in backups))
        self.assertEqual(second.read_bytes(), b"old second\n")


class CommandTests(unittest.TestCase):
    def test_stalled_process_is_stopped_at_the_deadline(self):
        started = time.monotonic()
        self.assertFalse(hardware._command(sys.executable, "-I", "-c", "import time; time.sleep(30)", timeout=0.1))
        self.assertLess(time.monotonic() - started, 3)

    def test_profile_command_has_a_deadline(self):
        with patch.object(hardware.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(hardware.set_profile("card", "profile"))
        run.assert_called_once_with(["pactl", "set-card-profile", "card", "profile"],
                                    capture_output=True, timeout=4.0)

    def test_codec_command_has_a_deadline_and_keeps_json_argument(self):
        with patch.object(hardware.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(hardware.bt_switch_codec("card", "codec"))
        run.assert_called_once_with(["pactl", "send-message", "/card/card/bluez", "switch-codec", '"codec"'],
                                    capture_output=True, timeout=4.0)

    def test_command_errors_return_failure(self):
        for method, arguments in ((hardware.set_profile, ("card", "profile")),
                                  (hardware.bt_switch_codec, ("card", "codec"))):
            for error in (OSError("missing command"), subprocess.TimeoutExpired("pactl", 4)):
                with self.subTest(method=method.__name__, error=error), \
                        patch.object(hardware.subprocess, "run", side_effect=error):
                    self.assertFalse(method(*arguments))

    def test_rejected_commands_return_failure(self):
        with patch.object(hardware.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            self.assertFalse(hardware.set_profile("card", "profile"))
            self.assertFalse(hardware.bt_switch_codec("card", "codec"))


if __name__ == "__main__":
    unittest.main()
