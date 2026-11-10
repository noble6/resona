"""Offline update tests; no network request or real installation is performed."""
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import updater


class RelaunchTests(unittest.TestCase):
    def wait_for_file(self, path, seconds=5):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if path.exists():
                return True
            time.sleep(0.05)
        return False

    def test_relaunch_waits_for_slow_parent_exit_and_preserves_arguments(self):
        for hidden in (False, True):
            with self.subTest(hidden=hidden), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                marker, ready = root / "launched.json", root / "ready"
                launcher = root / "launcher ' ; % name"
                launcher.write_text(f"#!{sys.executable}\n" +
                                    "import json, os, sys\nfrom pathlib import Path\n" +
                                    f"target = Path({str(marker)!r})\n" +
                                    "temporary = target.with_suffix('.tmp')\n" +
                                    "temporary.write_text(json.dumps(dict(args=sys.argv[1:], sid=os.getsid(0))))\n" +
                                    "temporary.replace(target)\n")
                launcher.chmod(0o755)
                parent = subprocess.Popen(
                    [sys.executable, "-c", """
import sys
from pathlib import Path
from resona import updater
updater.relaunch(sys.argv[1], hidden=sys.argv[3] == '1')
Path(sys.argv[2]).write_text('ready')
sys.stdin.read()
""", str(launcher), str(ready), str(int(hidden))],
                    env=dict(os.environ, PYTHONPATH=str(Path(updater.__file__).resolve().parents[1])),
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                )
                try:
                    self.assertTrue(self.wait_for_file(ready), "test parent did not schedule relaunch")
                    time.sleep(2.3)
                    self.assertFalse(marker.exists(), "replacement started before the old process exited")
                    parent.stdin.close()
                    # Do not reap the parent yet: a zombie must not block the replacement.
                    self.assertTrue(self.wait_for_file(marker), "replacement did not start after parent exit")
                    result = json.loads(marker.read_text())
                    self.assertEqual(result["args"], ["--hidden"] if hidden else [])
                    self.assertNotEqual(result["sid"], os.getsid(0))
                finally:
                    if not parent.stdin.closed:
                        parent.stdin.close()
                    parent.wait(timeout=5)
                    self.wait_for_file(marker)
                    parent.stderr.close()

    def test_invalid_launcher_is_rejected_before_scheduling(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nonexecutable = root / "not-executable"
            nonexecutable.write_text("not a launcher")
            for launcher in (root / "missing", nonexecutable, root):
                with self.subTest(launcher=launcher), patch.object(updater.subprocess, "Popen") as spawn:
                    with self.assertRaisesRegex(RuntimeError, "launcher"):
                        updater.relaunch(str(launcher), hidden=False)
                    spawn.assert_not_called()

    def test_reused_pid_does_not_block_relaunch(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "launched"
            launcher = Path(directory) / "launcher"
            launcher.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n")
            launcher.chmod(0o755)
            result = subprocess.run(
                [sys.executable, "-I", "-c", updater._RELAUNCH_SCRIPT,
                 str(os.getpid()), "different-start-time", str(launcher)],
                capture_output=True, text=True, timeout=5,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(marker.exists())


class UpdateTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(updater.release, "verify")
        self.verifier = patcher.start()
        self.addCleanup(patcher.stop)

    def archive(self, extra=None):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w:gz") as archive:
            for name, content in {
                "release/install.sh": b"#!/bin/sh\nexit 0\n",
                "release/app/resona/__init__.py": b'__version__ = "9.0.0"\n',
            }.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            if extra is not None:
                archive.addfile(extra)
        return data.getvalue()

    def info(self, tag="v9.0.0"):
        archive, bundle = updater.release.urls(tag)
        return {"version": tag.lstrip("vV"), "tag": tag, "commit": "a" * 40,
                "tarball": archive, "attestation": bundle}

    def test_workspace_is_private_and_removed_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            cache.mkdir()
            sentinel = cache / "unrelated"
            sentinel.write_text("keep")
            prefix = Path(directory) / "prefix"
            workspaces = []

            def install(args, **kwargs):
                source = Path(kwargs["cwd"])
                self.assertTrue((source / "install.sh").is_file())
                self.assertEqual(kwargs["env"]["PREFIX"], str(prefix))
                workspaces.append(source.parent.parent)
                return subprocess.CompletedProcess(args, 0, "", "")

            with patch.object(updater, "CACHE", cache), \
                    patch.object(updater, "APP_DIR", prefix / "share/resona"), \
                    patch.object(updater, "install_kind", return_value="user"), \
                    patch.object(updater, "_get", side_effect=lambda *a, **kw: io.BytesIO(self.archive())), \
                    patch.object(updater.subprocess, "run", side_effect=install):
                self.assertEqual(updater.install(self.info()), str(prefix / "bin/resona"))
            self.assertEqual(sentinel.read_text(), "keep")
            self.assertTrue(workspaces)
            self.assertTrue(all(not path.exists() for path in workspaces))
            self.assertEqual(list(cache.iterdir()), [sentinel])

    def test_failed_install_cleans_only_its_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            cache.mkdir()
            sentinel = cache / "unrelated"
            sentinel.write_text("keep")
            with patch.object(updater, "CACHE", cache), \
                    patch.object(updater, "install_kind", return_value="user"), \
                    patch.object(updater, "_get", side_effect=lambda *a, **kw: io.BytesIO(self.archive())), \
                    patch.object(updater.subprocess, "run", side_effect=subprocess.TimeoutExpired("install", 600)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    updater.install(self.info())
            self.assertEqual(list(cache.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_text(), "keep")

    def assert_rejected(self, archive, message, **limits):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            with patch.object(updater, "CACHE", cache), \
                    patch.object(updater, "install_kind", return_value="user"), \
                    patch.object(updater, "_get", side_effect=lambda *a, **kw: io.BytesIO(archive)), \
                    patch.object(updater.subprocess, "run") as install, \
                    patch.multiple(updater, **limits):
                with self.assertRaisesRegex(RuntimeError, message):
                    updater.install(self.info())
                install.assert_not_called()
            self.assertEqual(list(cache.iterdir()), [])

    def test_download_limit_is_enforced_without_content_length(self):
        self.assert_rejected(self.archive(), "size limit", MAX_DOWNLOAD_BYTES=8)

    def test_expansion_and_entry_count_are_bounded(self):
        self.assert_rejected(self.archive(), "extraction limit", MAX_EXTRACTED_BYTES=8)
        self.assert_rejected(self.archive(), "extraction limit", MAX_ARCHIVE_MEMBERS=1)

    def test_archive_paths_and_links_are_checked_before_extraction(self):
        for name, kind in (("../escape", tarfile.REGTYPE), ("/escape", tarfile.REGTYPE),
                           ("release/link", tarfile.SYMTYPE), ("release/hard", tarfile.LNKTYPE),
                           ("release/fifo", tarfile.FIFOTYPE)):
            with self.subTest(name=name):
                member = tarfile.TarInfo(name)
                member.type = kind
                member.linkname = "install.sh"
                with tempfile.TemporaryDirectory() as directory:
                    archive = Path(directory) / "bad.tar.gz"
                    archive.write_bytes(self.archive(extra=member))
                    output = Path(directory) / "output"
                    with self.assertRaises(RuntimeError):
                        updater._extract(archive, output)
                    self.assertFalse(output.exists())

    def test_download_checks_declared_size_and_truncation(self):
        for data, length in ((b"small", str(updater.MAX_DOWNLOAD_BYTES + 1)), (b"short", "10")):
            response = io.BytesIO(data)
            response.headers = {"Content-Length": length}
            with self.subTest(length=length), tempfile.TemporaryDirectory() as directory:
                with patch.object(updater, "_get", return_value=response), self.assertRaises(RuntimeError):
                    updater._download(self.info()["tarball"], Path(directory) / "download")

    def test_release_metadata_is_validated_before_download(self):
        for changes in (
            {"tag": "main"}, {"version": "8.0.0"},
            {"tarball": "https://example.com/release.tar.gz"},
            {"tarball": f"https://api.github.com/repos/{updater.REPO}/tarball/main"},
            {"tarball": self.info()["tarball"] + "?other=1"},
        ):
            with self.subTest(changes=changes), \
                    patch.object(updater, "install_kind", return_value="user"), \
                    patch.object(updater, "_get") as download, \
                    patch.object(updater.subprocess, "run") as install:
                with self.assertRaises(RuntimeError):
                    updater.install(self.info() | changes)
                download.assert_not_called()
                install.assert_not_called()

    def test_source_version_mismatch_never_runs_installer(self):
        info = self.info("v8.0.0")
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            with patch.object(updater, "CACHE", cache), \
                    patch.object(updater, "install_kind", return_value="user"), \
                    patch.object(updater, "_get", side_effect=lambda *a, **kw: io.BytesIO(self.archive())), \
                    patch.object(updater.subprocess, "run") as install:
                with self.assertRaisesRegex(RuntimeError, "source version"):
                    updater.install(info)
                install.assert_not_called()
            self.assertEqual(list(cache.iterdir()), [])

    def test_check_validates_github_metadata(self):
        release = {"tag_name": "v9.0.0", "tarball_url": f"https://api.github.com/repos/{updater.REPO}/tarball/v9.0.0",
                   "assets": [{"name": url.rsplit("/", 1)[1], "browser_download_url": url, "state": "uploaded"}
                              for url in (self.info()["tarball"], self.info()["attestation"])]}
        responses = [release, {"object": {"type": "commit", "sha": "a" * 40}}]
        with patch.object(updater, "_get", side_effect=lambda *a, **kw: io.BytesIO(json.dumps(responses.pop(0)).encode())):
            info = updater.check()
        self.assertTrue(info["available"])
        self.assertEqual(info["version"], "9.0.0")
        self.assertEqual(info["commit"], "a" * 40)
        release["tarball_url"] = "https://example.com/not-this-project"
        with patch.object(updater, "_get", return_value=io.BytesIO(json.dumps(release).encode())):
            with self.assertRaisesRegex(RuntimeError, "download location"):
                updater.check()

    def test_unpublished_or_invalid_release_responses_are_rejected(self):
        for response in ([], None, {"draft": True}, {"prerelease": True}):
            with self.subTest(response=response), \
                    patch.object(updater, "_get", return_value=io.BytesIO(json.dumps(response).encode())):
                with self.assertRaisesRegex(RuntimeError, "stable published release"):
                    updater.check()

    def test_failed_attestation_never_extracts_or_runs_installer(self):
        self.verifier.side_effect = RuntimeError("invalid attestation")
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(updater, "CACHE", Path(directory)), \
                    patch.object(updater, "install_kind", return_value="user"), \
                    patch.object(updater, "_get", side_effect=lambda *a, **kw: io.BytesIO(self.archive())), \
                    patch.object(updater, "_extract") as extract, \
                    patch.object(updater.subprocess, "run") as installer:
                with self.assertRaisesRegex(RuntimeError, "invalid attestation"):
                    updater.install(self.info())
                extract.assert_not_called()
                installer.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_attestation_download_has_its_own_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(updater, "CACHE", Path(directory)), \
                    patch.object(updater, "install_kind", return_value="user"), \
                    patch.object(updater, "_get", side_effect=lambda *a, **kw: io.BytesIO(self.archive())), \
                    patch.object(updater.release, "MAX_BUNDLE_BYTES", 8), \
                    patch.object(updater.subprocess, "run") as installer:
                with self.assertRaisesRegex(RuntimeError, "size limit"):
                    updater.install(self.info())
                self.verifier.assert_not_called()
                installer.assert_not_called()

    def test_current_unsigned_release_does_not_request_an_attestation(self):
        metadata = {"tag_name": "v" + updater.__version__,
                    "tarball_url": f"https://api.github.com/repos/{updater.REPO}/tarball/v{updater.__version__}"}
        with patch.object(updater, "_get", return_value=io.BytesIO(json.dumps(metadata).encode())) as get:
            self.assertFalse(updater.check()["available"])
            get.assert_called_once_with(updater.API)

    def test_new_unsigned_release_is_not_offered_as_an_installable_update(self):
        metadata = {"tag_name": "v9.0.0", "tarball_url": f"https://api.github.com/repos/{updater.REPO}/tarball/v9.0.0"}
        with patch.object(updater, "_get", return_value=io.BytesIO(json.dumps(metadata).encode())):
            with self.assertRaisesRegex(RuntimeError, "lacks attested update files"):
                updater.check()


if __name__ == "__main__":
    unittest.main()
