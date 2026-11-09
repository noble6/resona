"""Atomic UI publication tests."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import shm


class PublicationTests(unittest.TestCase):
    def test_payload_is_written_only_inside_publication_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            state = shm.SharedState(str(Path(directory) / "shm"))
            store = shm._store_u32

            def checked_store(address, value, order):
                offset = address - state._address
                if offset not in (shm.OFF_CONTROL_SEQ, shm.OFF_SEQ):
                    self.assertEqual(state._u32(shm.OFF_CONTROL_SEQ) & 1, 1)
                store(address, value, order)

            try:
                with patch.object(shm, "_store_u32", checked_store):
                    state.write({"eq0": 6, "eq1": 3})
                    state.write_corr([{"type": "PK", "freq": 1000, "gain": 6, "q": 1}])
                self.assertEqual(state._u32(shm.OFF_CONTROL_SEQ) & 1, 0)
                self.assertEqual(state._u32(shm.OFF_SEQ), 2)
                self.assertEqual(state.params[shm.INDEX["eq0"]], 6)
                self.assertEqual(state.corr[0, 1], 1000)
                before = state._u32(shm.OFF_CONTROL_SEQ)
                with self.assertRaises((ValueError, TypeError)):
                    state.write({"eq0": "invalid"})
                self.assertEqual(state._u32(shm.OFF_CONTROL_SEQ), before)
            finally:
                state.close()


if __name__ == "__main__":
    unittest.main()
