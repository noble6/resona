"""Desktop Entry command quoting regressions."""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona.desktop import exec_line


class DesktopTests(unittest.TestCase):
    def test_paths_with_spaces_are_separate_arguments(self):
        self.assertEqual(exec_line(["/home/test user/bin/resona", "--hidden"]),
                         '"/home/test user/bin/resona" "--hidden"')

    def test_exec_metacharacters_round_trip(self):
        args = ['/home/test $user/"quoted"/back\\slash/`name`/100%/resona', "--hidden"]
        encoded = exec_line(args)
        # Undo the Desktop Entry string layer, then the Exec quoting layer.
        decoded = encoded.replace("\\\\", "\\")
        script = 'set -- ' + decoded.replace("%%", "%") + '; printf \'%s\\0\' "$@"'
        result = subprocess.run(["sh", "-c", script], check=True, capture_output=True)
        self.assertEqual(result.stdout.decode().split("\0")[:-1], args)


if __name__ == "__main__":
    unittest.main()
