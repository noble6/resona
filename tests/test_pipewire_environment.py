"""Run live tests and verify they leave inherited desktop directories untouched."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EnvironmentTests(unittest.TestCase):
    def test_live_harness_keeps_state_and_caches_private(self):
        with tempfile.TemporaryDirectory(prefix="resona-isolation-") as directory:
            root = Path(directory)
            env = dict(os.environ)
            homes = []
            for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME"):
                home = root / key.lower()
                home.mkdir()
                (home / "sentinel").write_text("untouched")
                homes.append(home)
                env[key] = str(home)
            temporary = root / "temporary"
            temporary.mkdir()
            env["TMPDIR"] = str(temporary)
            result = subprocess.run(["bash", str(ROOT / "tests/run_pipewire.sh")],
                                    cwd=ROOT, env=env, timeout=180)
            self.assertEqual(result.returncode, 0, "live test harness failed")
            for home in homes:
                with self.subTest(home=home.name):
                    self.assertEqual(sorted(str(p.relative_to(home)) for p in home.rglob("*")), ["sentinel"])
                    self.assertEqual((home / "sentinel").read_text(), "untouched")
            self.assertEqual(list(temporary.glob("resona-tests.*")), [], "private runtime was not removed")


if __name__ == "__main__":
    unittest.main()
