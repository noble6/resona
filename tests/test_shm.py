"""Atomic UI publication tests."""
import sys
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import shm


class PublicationTests(unittest.TestCase):
    def test_close_waits_for_inflight_publication(self):
        # A broken implementation can segfault; keep the race in a child process.
        code = r'''
import resource, sys, threading
from resona import shm
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
state = shm.SharedState(sys.argv[1])
entered, resume, closing, closed = (threading.Event() for _ in range(4))
store = shm._store_u32
errors = []
def paused_store(address, value, order):
    store(address, value, order)
    if address == state._address + shm.OFF_CONTROL_SEQ and value & 1:
        entered.set()
        assert resume.wait(5), "writer was not resumed"
shm._store_u32 = paused_store
def write():
    try:
        state.write({"eq0": 3})
    except BaseException as error:
        errors.append(error)
def close():
    closing.set()
    state.close()
    closed.set()
writer = threading.Thread(target=write, daemon=True)
closer = threading.Thread(target=close, daemon=True)
writer.start()
assert entered.wait(5), "writer never reached publication"
closer.start()
try:
    assert closing.wait(5), "close never started"
    assert not closed.wait(0.2), "mapping closed during publication"
finally:
    resume.set()
    writer.join(5)
    closer.join(5)
assert not writer.is_alive() and not closer.is_alive(), "lifecycle deadlock"
assert not errors, errors
assert state.closed and closed.is_set()
state.close()
state.write({"eq0": 6})
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", code, str(Path(directory) / "shm")],
                env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "app")),
                capture_output=True, text=True, timeout=15,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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


class ReaderLifetimeTests(unittest.TestCase):
    def test_close_waits_for_every_inflight_reader(self):
        code = r'''
import resource, sys, threading
from resona import shm
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
state = shm.SharedState(sys.argv[1])
kind = sys.argv[2]
entered, resume, closing, closed = (threading.Event() for _ in range(4))
errors, results = [], []
def pause():
    entered.set()
    assert resume.wait(5), "reader was not resumed"
if kind in ("heartbeat", "sample_rate", "out_channels", "meters"):
    unpack = shm.struct.unpack_from
    def paused_unpack(*args, **kwargs):
        pause()
        return unpack(*args, **kwargs)
    shm.struct.unpack_from = paused_unpack
elif kind == "ieq_gains":
    original = state.ieq
    class PausedArray:
        def __iter__(self):
            pause()
            return iter(original)
    state.ieq = PausedArray()
else:
    arange = shm.np.arange
    def paused_arange(*args, **kwargs):
        pause()
        return arange(*args, **kwargs)
    shm.np.arange = paused_arange
def read():
    try:
        value = getattr(state, kind)
        results.append(value(8) if kind == "latest" else value() if callable(value) else value)
    except BaseException as error:
        errors.append(error)
def close():
    closing.set()
    state.close()
    closed.set()
reader = threading.Thread(target=read, daemon=True)
closer = threading.Thread(target=close, daemon=True)
reader.start()
assert entered.wait(5), "reader never reached mapped data"
closer.start()
try:
    assert closing.wait(5), "close never started"
    assert not closed.wait(0.1), "mapping closed during read"
finally:
    resume.set()
    reader.join(5)
    closer.join(5)
assert not reader.is_alive() and not closer.is_alive(), "lifecycle deadlock"
assert not errors, errors
assert len(results) == 1
assert state.closed and closed.is_set()
assert state.heartbeat == 0 and state.sample_rate == 48000 and state.out_channels == 2
assert state.ieq_gains() == [0.0] * shm.NBANDS
assert not any(state.meters().values())
a, b = state.latest(8)
assert len(a) == len(b) == 8 and not a.any() and not b.any()
if kind == "latest":
    assert all(array.flags.owndata for array in results[0])
state.close()
'''
        for reader in ("heartbeat", "sample_rate", "out_channels", "meters", "ieq_gains", "latest"):
            with self.subTest(reader=reader), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [sys.executable, "-c", code, str(Path(directory) / "shm"), reader],
                    env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "app")),
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
