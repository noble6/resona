"""Offline checks for private audio fixture readiness; no audio server is started."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FixtureTests(unittest.TestCase):
    def run_fixture(self, mode, seconds=3):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pactl = root / "pactl"
            pactl.write_text(f"#!{sys.executable}\n" + '''
import os,sys,time
from pathlib import Path
root=Path(os.environ['FIXTURE_ROOT'])
mode=os.environ['FIXTURE_MODE']
counter=root/'loads'
if sys.argv[1:]==['list','short','sinks']:
    if mode=='existing':
        print('1\\tci_hardware\\tfixture')
    elif (root/'loaded').exists():
        path=root/'queries'
        count=int(path.read_text())+1 if path.exists() else 1
        path.write_text(str(count))
        if mode!='delayed' or count>=3:
            print('1\\tci_hardware\\tfixture')
    sys.exit(0)
assert sys.argv[1:]==['load-module','module-null-sink','sink_name=ci_hardware']
count=int(counter.read_text())+1 if counter.exists() else 1
counter.write_text(str(count))
if mode=='stalled':
    time.sleep(10)
if mode=='permanent' or mode=='transient' and count<=2:
    print('Failure: Not supported',file=sys.stderr)
    sys.exit(1)
(root/'loaded').touch()
print('1')
''')
            pactl.chmod(0o755)
            result = subprocess.run(
                ["bash", "-euo", "pipefail", "-c",
                 'source "$1"; runtime="$2"; wait_for_test_sink ci_hardware "$3"',
                 "fixture-test", str(ROOT / "tests/pipewire_fixture.sh"), str(root), str(seconds)],
                env=dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                         FIXTURE_ROOT=str(root), FIXTURE_MODE=mode),
                capture_output=True, text=True, timeout=8,
            )
            loads = int((root / "loads").read_text()) if (root / "loads").exists() else 0
            return result, loads

    def test_transient_unsupported_response_is_retried_until_sink_exists(self):
        result, loads = self.run_fixture("transient")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(loads, 3)

    def test_successful_load_is_not_repeated_while_node_is_announced(self):
        result, loads = self.run_fixture("delayed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(loads, 1)

    def test_existing_sink_does_not_load_another_module(self):
        result, loads = self.run_fixture("existing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(loads, 0)

    def test_permanent_failure_is_not_hidden(self):
        result, loads = self.run_fixture("permanent", seconds=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertGreater(loads, 0)
        self.assertIn("did not become ready", result.stderr)

    def test_stalled_command_has_a_timeout(self):
        started = time.monotonic()
        result, loads = self.run_fixture("stalled", seconds=1)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(loads, 1)
        self.assertLess(time.monotonic() - started, 5)


if __name__ == "__main__":
    unittest.main()
