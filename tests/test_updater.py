"""Offline update tests; no network request or real installation is performed."""
import io
import json
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
        info = self.info() | {"tag": "v8.0.0", "version": "8.0.0",
                              "tarball": f"https://api.github.com/repos/{updater.REPO}/tarball/v8.0.0"}
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache"
            with patch.object(updater, "CACHE", cache), \
                    patch.object(updater, "install_kind", return_value="user"), \
                    patch.object(updater, "_get", return_value=io.BytesIO(self.archive())), \
                    patch.object(updater.subprocess, "run") as install:
                with self.assertRaisesRegex(RuntimeError, "source version"):
                    updater.install(info)
                install.assert_not_called()
            self.assertEqual(list(cache.iterdir()), [])

    def test_check_validates_github_metadata(self):
        release = {"tag_name": "v9.0.0", "tarball_url": self.info()["tarball"]}
        with patch.object(updater, "_get", return_value=io.BytesIO(json.dumps(release).encode())):
            info = updater.check()
        self.assertTrue(info["available"])
        self.assertEqual(info["version"], "9.0.0")
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


if __name__ == "__main__":
    unittest.main()
