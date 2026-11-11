"""Routing lifecycle tests with no live PipeWire connection."""
import sys
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import pipeline


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.pipe = pipeline.Pipeline("/unused")
        self.pipe.proc = Mock(poll=Mock(return_value=None))

    def test_stop_during_readiness_does_not_reclaim_default(self):
        def sink_exists(name):
            self.pipe.stop(restore_default=False)
            return True

        with patch.object(pipeline, "sink_exists", side_effect=sink_exists), \
                patch.object(pipeline, "set_default_sink") as set_default:
            self.assertFalse(self.pipe.wait_ready())
            set_default.assert_not_called()

    def test_replaced_process_does_not_reclaim_default(self):
        def sink_exists(name):
            self.pipe.proc = Mock(poll=Mock(return_value=None))
            return True

        with patch.object(pipeline, "sink_exists", side_effect=sink_exists), \
                patch.object(pipeline, "set_default_sink") as set_default:
            self.assertFalse(self.pipe.wait_ready())
            set_default.assert_not_called()

    def test_ready_process_sets_default_and_saves_previous(self):
        with patch.object(pipeline, "sink_exists", return_value=True), \
                patch.object(pipeline, "default_sink", return_value="physical"), \
                patch.object(pipeline, "set_default_sink") as set_default:
            self.assertTrue(self.pipe.wait_ready())
            self.assertEqual(self.pipe.previous_default, "physical")
            set_default.assert_called_once_with(self.pipe.sink_name)

    def test_failed_default_change_does_not_report_ready(self):
        self.pipe.previous_default = "saved-output"
        with patch.object(pipeline, "sink_exists", return_value=True), \
                patch.object(pipeline, "default_sink", return_value="physical"), \
                patch.object(pipeline, "set_default_sink", return_value=False):
            self.assertFalse(self.pipe.wait_ready())
        self.assertEqual(self.pipe.previous_default, "saved-output")

    def test_readiness_without_takeover_does_not_change_default(self):
        with patch.object(pipeline, "sink_exists", return_value=True), \
                patch.object(pipeline, "set_default_sink") as set_default:
            self.assertTrue(self.pipe.wait_ready(make_default=False))
        set_default.assert_not_called()


class DefaultOutputTests(unittest.TestCase):
    def test_successful_command_reports_success(self):
        with patch.object(pipeline.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertTrue(pipeline.set_default_sink("physical"))
        run.assert_called_once_with(["pactl", "set-default-sink", "physical"], capture_output=True, timeout=3)

    def test_rejected_command_reports_failure(self):
        with patch.object(pipeline.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            self.assertFalse(pipeline.set_default_sink("missing"))

    def test_command_errors_report_failure(self):
        for error in (OSError("pactl unavailable"), subprocess.TimeoutExpired("pactl", 3)):
            with self.subTest(error=error), patch.object(pipeline.subprocess, "run", side_effect=error):
                self.assertFalse(pipeline.set_default_sink("physical"))


if __name__ == "__main__":
    unittest.main()
