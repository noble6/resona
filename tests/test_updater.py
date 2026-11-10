"""Offline update tests; no network request or real installation is performed."""
import io
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import updater


class UpdateTests(unittest.TestCase):
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

    def info(self):
        return {"version": "9.0.0", "tag": "v9.0.0",
                "tarball": f"https://api.github.com/repos/{updater.REPO}/tarball/v9.0.0"}

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
                    patch.object(updater, "_get", return_value=io.BytesIO(self.archive())), \
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
                    patch.object(updater, "_get", return_value=io.BytesIO(self.archive())), \
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
                    patch.object(updater, "_get", return_value=io.BytesIO(archive)), \
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


if __name__ == "__main__":
    unittest.main()
