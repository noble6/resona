"""Routing lifecycle tests with no live PipeWire connection."""
import sys
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


if __name__ == "__main__":
    unittest.main()
