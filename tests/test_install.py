"""Installer regression tests; never touch the user's installation or audio server."""
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("resona_installer", ROOT / "packaging/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
ARTIFACTS = (
    "lib/resona/resona.so", "share/resona", "bin/resona",
    "share/icons/hicolor/scalable/apps/resona.svg", "share/applications/resona.desktop",
)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        for name in ("resona", "qml", "fonts", "icons"):
            folder = self.source / "app" / name
            folder.mkdir(parents=True)
            (folder / "payload").write_text("new " + name)
        (self.source / "app/main.py").write_text("print('new app')\n")
        (self.source / "app/icons/resona.svg").write_text("<svg/>")
        (self.source / "engine").mkdir()
        (self.source / "engine/resona.so").write_bytes(b"new plugin")
        self.prefix = self.root / "prefix with 'quotes' and % fields"
        self.prefix.mkdir()
        (self.prefix / "unrelated").write_text("keep")

    def seed_previous(self):
        for relative in ARTIFACTS:
            target = self.prefix / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative == "share/resona":
                target.mkdir()
                target = target / "old.py"
            target.write_text("old " + relative)
            target.chmod(0o640)

    def snapshot(self):
        return {
            str(path.relative_to(self.prefix)): (
                "link", os.readlink(path)
            ) if path.is_symlink() else ("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            for path in self.prefix.rglob("*") if path.is_symlink() or path.is_file()
        }

    def assert_clean(self):
        self.assertEqual(list(self.prefix.rglob(".resona-install-*")), [])
        self.assertEqual((self.prefix / "unrelated").read_text(), "keep")

    def test_fresh_install_stages_all_artifacts_and_quotes_launcher(self):
        cache = self.source / "app/resona/__pycache__"
        cache.mkdir()
        (cache / "ignore.pyc").write_bytes(b"cache")
        installer.install(self.source, self.prefix)
        for relative in ARTIFACTS:
            self.assertTrue((self.prefix / relative).exists(), relative)
        self.assertFalse((self.prefix / "share/resona/resona/__pycache__").exists())
        self.assertEqual((self.prefix / "lib/resona/resona.so").read_bytes(), b"new plugin")
        self.assertEqual(stat.S_IMODE((self.prefix / "bin/resona").stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE((self.prefix / "share/applications/resona.desktop").stat().st_mode), 0o644)
        fake_bin = self.root / "tools"
        fake_bin.mkdir()
        python = fake_bin / "python3"
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$RESONA_PLUGIN" "$@"\n')
        python.chmod(0o755)
        result = subprocess.run([str(self.prefix / "bin/resona"), "argument with spaces"],
                                env=dict(os.environ, PATH=str(fake_bin)), capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [str(self.prefix / "lib/resona/resona.so"),
                                                     str(self.prefix / "share/resona/main.py"), "argument with spaces"])
        self.assertIn("%%", (self.prefix / "share/applications/resona.desktop").read_text())
        self.assert_clean()

    def test_upgrade_replaces_old_app_without_touching_other_files(self):
        self.seed_previous()
        installer.install(self.source, self.prefix)
        self.assertFalse((self.prefix / "share/resona/old.py").exists())
        self.assertTrue((self.prefix / "share/resona/main.py").exists())
        self.assert_clean()

    def test_staging_failure_preserves_previous_installation(self):
        self.seed_previous()
        before = self.snapshot()
        (self.source / "app/icons/resona.svg").unlink()
        with self.assertRaises(FileNotFoundError):
            installer.install(self.source, self.prefix)
        self.assertEqual(self.snapshot(), before)
        self.assert_clean()

    def test_each_failed_rename_restores_upgrade_or_fresh_install(self):
        replace = os.replace
        for existing in (False, True):
            if existing:
                self.seed_previous()
            before = self.snapshot()
            for failed_call in range(1, len(ARTIFACTS) * (2 if existing else 1) + 1):
                count = 0

                def fail_once(source, destination):
                    nonlocal count
                    count += 1
                    if count == failed_call:
                        raise PermissionError("injected publish permission failure")
                    return replace(source, destination)

                with self.subTest(existing=existing, failed_call=failed_call), \
                        patch.object(installer.os, "replace", side_effect=fail_once):
                    with self.assertRaises(PermissionError):
                        installer.install(self.source, self.prefix)
                self.assertEqual(self.snapshot(), before)
                self.assert_clean()

    def test_existing_symlink_is_restored_without_touching_its_target(self):
        self.seed_previous()
        destination = self.prefix / "bin/resona"
        destination.unlink()
        outside = self.root / "outside"
        outside.write_text("keep outside")
        destination.symlink_to(outside)
        before = self.snapshot()
        replace = os.replace

        def fail_late(source, target):
            if Path(source).name == "new" and Path(target).name == "resona.desktop":
                raise OSError("late failure")
            return replace(source, target)

        with patch.object(installer.os, "replace", side_effect=fail_late), self.assertRaises(OSError):
            installer.install(self.source, self.prefix)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(outside.read_text(), "keep outside")
        self.assert_clean()

    def test_real_sigterm_during_publication_restores_previous_files(self):
        self.seed_previous()
        before = self.snapshot()
        code = '''
import importlib.util, os, signal, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("installer", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
signal.signal(signal.SIGTERM, module.interrupted)
replace = os.replace
def interrupt(source, destination):
    replace(source, destination)
    if Path(source).name == "new":
        os.kill(os.getpid(), signal.SIGTERM)
module.os.replace = interrupt
try:
    module.install(Path(sys.argv[2]), Path(sys.argv[3]))
except InterruptedError:
    sys.exit(42)
'''
        result = subprocess.run([sys.executable, "-c", code, str(ROOT / "packaging/install.py"),
                                 str(self.source), str(self.prefix)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assert_clean()

    def test_failed_rollback_preserves_backups_for_manual_recovery(self):
        self.seed_previous()
        replace = os.replace

        def fail_publish_and_recovery(source, destination):
            if Path(source).name == "new" or Path(source).name == "previous":
                raise PermissionError("injected recovery failure")
            return replace(source, destination)

        with patch.object(installer.os, "replace", side_effect=fail_publish_and_recovery):
            with self.assertRaisesRegex(RuntimeError, "Rollback incomplete.*backup workspace"):
                installer.install(self.source, self.prefix)
        backups = list(self.prefix.rglob(".resona-install-*/previous"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "old lib/resona/resona.so")

    def test_prefix_lock_serializes_installers(self):
        code = '''
import importlib.util, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("installer", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print("ready", flush=True)
module.install(Path(sys.argv[2]), Path(sys.argv[3]))
'''
        with installer.prefix_lock(self.prefix):
            child = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "packaging/install.py"),
                                      str(self.source), str(self.prefix)], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), "ready")
                with self.assertRaises(subprocess.TimeoutExpired):
                    child.wait(timeout=0.1)
                self.assertFalse((self.prefix / "bin/resona").exists())
            except BaseException:
                child.kill()
                child.communicate()
                raise
        try:
            _, error = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, error)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()
        self.assertTrue((self.prefix / "bin/resona").exists())
        self.assert_clean()

    def shell_environment(self):
        shutil.copy(ROOT / "install.sh", self.source / "install.sh")
        (self.source / "packaging").mkdir(exist_ok=True)
        shutil.copy(ROOT / "packaging/install.py", self.source / "packaging/install.py")
        shutil.copy(ROOT / "app/resona/desktop.py", self.source / "app/resona/desktop.py")
        tools = self.root / "shell-tools"
        tools.mkdir()
        for name, content in {
            "pipewire": "exit 0", "pactl": "exit 0", "make": "exit 0",
            "update-desktop-database": "exit 1",
            "python3": 'if [ "$1" = "-c" ]; then exit 0; fi\nexec ' + shlex.quote(sys.executable) + ' "$@"',
        }.items():
            path = tools / name
            path.write_text("#!/bin/sh\n" + content + "\n")
            path.chmod(0o755)
        return dict(os.environ, PREFIX=str(self.prefix), PATH=str(tools) + os.pathsep + os.environ["PATH"])

    def test_shell_entrypoint_installs_with_stubbed_preflight_and_build(self):
        result = subprocess.run(["sh", str(self.source / "install.sh")], env=self.shell_environment(),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Resona installed to", result.stdout)
        self.assertTrue((self.prefix / "share/resona/main.py").exists())
        self.assert_clean()

    def test_shell_build_failure_leaves_installation_unchanged(self):
        self.seed_previous()
        before = self.snapshot()
        env = self.shell_environment()
        (self.root / "shell-tools/make").write_text("#!/bin/sh\nexit 42\n")
        result = subprocess.run(["sh", str(self.source / "install.sh")], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assert_clean()

    def test_shell_missing_payload_leaves_installation_unchanged(self):
        self.seed_previous()
        before = self.snapshot()
        env = self.shell_environment()
        (self.source / "app/icons/resona.svg").unlink()
        result = subprocess.run(["sh", str(self.source / "install.sh")], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.snapshot(), before)
        self.assert_clean()

    def test_shell_preflight_failure_leaves_installation_unchanged(self):
        self.seed_previous()
        before = self.snapshot()
        env = self.shell_environment()
        (self.root / "shell-tools/python3").write_text("#!/bin/sh\nexit 1\n")
        result = subprocess.run(["sh", str(self.source / "install.sh")], env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing deps or Qt < 6.7", result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assert_clean()

    def test_uninstall_keeps_user_settings_and_other_prefix_files(self):
        installer.install(self.source, self.prefix)
        config = self.root / "config"
        settings = config / "resona/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"keep": true}')
        tools = self.root / "uninstall-tools"
        tools.mkdir()
        pkill = tools / "pkill"
        pkill.write_text("#!/bin/sh\nexit 1\n")
        pkill.chmod(0o755)
        result = subprocess.run(["sh", str(ROOT / "uninstall.sh")], capture_output=True, text=True,
                                env=dict(os.environ, PREFIX=str(self.prefix), XDG_CONFIG_HOME=str(config),
                                         PATH=str(tools) + os.pathsep + os.environ["PATH"]), timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative in ARTIFACTS:
            self.assertFalse((self.prefix / relative).exists(), relative)
        self.assertEqual(settings.read_text(), '{"keep": true}')
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
