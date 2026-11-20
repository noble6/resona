"""Routing lifecycle tests with no live PipeWire connection."""
import sys
import re
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


class ConvolverConfigTests(unittest.TestCase):
    def test_gain_keeps_precision_across_config_rendering(self):
        for gain in (1e-7, 1 / 600000, 0.3535533905932738, 1.0):
            for channels in (1, 2, 4):
                with self.subTest(gain=gain, channels=channels):
                    nodes, _, _ = pipeline._ir_graph(
                        {"path": "/private/ir.wav", "channels": channels, "gain": gain})
                    rendered = [float(value) for node in nodes
                                for value in re.findall(r"\bgain = (\S+)", node)]
                    self.assertEqual(len(rendered), 4 if channels == 4 else 2)
                    self.assertEqual(rendered, [gain] * len(rendered))


class SinkVolumeTests(unittest.TestCase):
    def volume(self, text, mute="Mute: no\n"):
        with patch.object(pipeline, "_run", side_effect=[text, mute]):
            return pipeline.sink_volume_db("private_sink")

    def test_muted_sink_reports_silence(self):
        for mute in ("Mute: yes\n", "mute: yes\n"):
            with self.subTest(mute=mute):
                self.assertEqual(self.volume("Volume: front-left: 65536 / 100% / 0.00 dB", mute), -120)

    def test_unmuted_sink_keeps_volume(self):
        self.assertEqual(self.volume("Volume: front-left: 32768 / 50% / -18.06 dB"), -18.06)

    def test_zero_volume_reports_silence(self):
        self.assertEqual(self.volume("Volume: front-left: 0 / 0% / -inf dB"), -120)

    def test_missing_or_invalid_mute_response_does_not_claim_unmuted_volume(self):
        for mute in ("", "unavailable", "Mute: maybe"):
            with self.subTest(mute=mute):
                self.assertIsNone(self.volume("Volume: front-left: 65536 / 100% / 0.00 dB", mute))

    def test_failed_volume_query_returns_unknown(self):
        self.assertIsNone(self.volume(""))


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
