"""Attestation policy tests; no release is published and no installer is executed."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import release


class ReleaseTests(unittest.TestCase):
    def info(self):
        archive, bundle = release.urls("v9.0.0")
        return dict(tag="v9.0.0", version="9.0.0", commit="a" * 40, tarball=archive, attestation=bundle)

    def getter(self, values):
        def get(url):
            return io.BytesIO(json.dumps(values.pop(0)).encode())
        return get

    def test_lightweight_and_annotated_tags_resolve_to_immutable_commit(self):
        for values in ([{"object": {"type": "commit", "sha": "a" * 40}}],
                       [{"object": {"type": "tag", "sha": "b" * 40}}, {"object": {"type": "commit", "sha": "a" * 40}}]):
            self.assertEqual(release.resolve_commit(self.getter(values), "v9.0.0"), "a" * 40)
            self.assertEqual(values, [])

    def test_invalid_tag_targets_and_annotation_cycles_are_rejected(self):
        for obj in ({"type": "tree", "sha": "a" * 40}, {"type": "commit", "sha": "main"}, {}):
            with self.assertRaises(RuntimeError):
                release.resolve_commit(self.getter([{"object": obj}]), "v9.0.0")
        cycle = [{"object": {"type": "tag", "sha": "a" * 40}}] * 7
        with self.assertRaisesRegex(RuntimeError, "within the limit"):
            release.resolve_commit(self.getter(cycle), "v9.0.0")

    def test_metadata_size_is_bounded(self):
        with self.assertRaisesRegex(RuntimeError, "size limit"):
            release.read_json(lambda url: io.BytesIO(b" " * (release.MAX_METADATA_BYTES + 1)), "unused")

    def test_download_identity_is_exact_and_commit_is_required(self):
        self.assertEqual(release.validate_info(self.info()), self.info()["tarball"])
        for changes in ({"commit": "main"}, {"commit": ""}, {"tag": "main"}, {"version": "8.0.0"},
                        {"tarball": self.info()["tarball"] + "?other=1"},
                        {"attestation": "https://example.com/bundle"}):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                release.validate_info(self.info() | changes)

    def test_missing_duplicate_or_foreign_assets_are_rejected(self):
        assets = [{"name": url.rsplit("/", 1)[1], "browser_download_url": url, "state": "uploaded"}
                  for url in release.urls("v9.0.0")]
        for candidate in ([], assets[:1], assets + assets[:1],
                          [assets[0] | {"browser_download_url": "https://example.com/source"}, assets[1]]):
            with self.assertRaises(RuntimeError):
                release.update_files(self.getter([]), {"assets": candidate}, "v9.0.0")

    def test_gh_fallback_enforces_repo_workflow_tag_commit_and_hosted_runner(self):
        # gh is only consulted when the built-in verifier cannot judge the bundle
        with patch.object(release, "_verify_native", return_value=False), \
                patch.object(release.shutil, "which", return_value="/usr/bin/gh"), \
                patch.object(release.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as verify:
            release.verify(Path("archive"), Path("bundle"), self.info())
        command = verify.call_args.args[0]
        for flag, value in (("--repo", release.REPO),
                            ("--source-digest", "a" * 40), ("--source-ref", "refs/tags/v9.0.0"),
                            ("--bundle", "bundle"), ("--hostname", "github.com"),
                            ("--cert-identity", f"https://github.com/{release.WORKFLOW}@refs/tags/v9.0.0"),
                            ("--cert-oidc-issuer", "https://token.actions.githubusercontent.com"),
                            ("--predicate-type", "https://slsa.dev/provenance/v1")):
            self.assertEqual(command[command.index(flag) + 1], value)
        self.assertIn("--deny-self-hosted-runners", command)
        self.assertNotIn("--signer-workflow", command)
        self.assertEqual(verify.call_args.kwargs["timeout"], 120)

    def test_missing_verifier_failure_and_timeout_fail_closed(self):
        with patch.object(release, "_verify_native", return_value=False), \
                patch.object(release.shutil, "which", return_value=None), \
                self.assertRaisesRegex(RuntimeError, "update Resona manually"):
            release.verify(Path("archive"), Path("bundle"), self.info())
        with patch.object(release, "_verify_native", return_value=False), \
                patch.object(release.shutil, "which", return_value="gh"):
            for result in (subprocess.CompletedProcess([], 1), subprocess.TimeoutExpired("gh", 120)):
                with patch.object(release.subprocess, "run", **({"side_effect": result} if isinstance(result, Exception)
                                                               else {"return_value": result})):
                    with self.assertRaises(RuntimeError):
                        release.verify(Path("archive"), Path("bundle"), self.info())

    # ---------------------------------------------------------------- built-in verifier
    def real_info(self):
        archive, bundle = release.urls("v2.2.2")
        return dict(tag="v2.2.2", version="2.2.2", commit="97876d9147746d2fb20c0eb68fb9869a5e94362f",
                    tarball=archive, attestation=bundle)

    def test_native_verification_needs_no_gh(self):
        bundle = Path(__file__).resolve().parent / "fixtures/resona-v2.2.2.tar.gz.sigstore.json"
        with tempfile.TemporaryDirectory() as d, \
                patch.object(release.shutil, "which", return_value=None) as which, \
                patch.object(release, "_sha256_file",
                             return_value="2ded033118313062773369f179c45bc941441ee6bfcb6d32f08c62835868afac"):
            archive = Path(d) / "a.tar.gz"
            archive.write_bytes(b"stand-in for the 2.5 MB release archive")
            release.verify(archive, bundle, self.real_info())
            which.assert_not_called()

    def test_native_refusal_never_falls_back_to_gh(self):
        bundle = Path(__file__).resolve().parent / "fixtures/resona-v2.2.2.tar.gz.sigstore.json"
        with tempfile.TemporaryDirectory() as d, \
                patch.object(release.shutil, "which", return_value="/usr/bin/gh") as which, \
                patch.object(release.subprocess, "run") as run:
            archive = Path(d) / "a.tar.gz"
            archive.write_bytes(b"not the signed release")
            with self.assertRaisesRegex(RuntimeError, "verification failed"):
                release.verify(archive, bundle, self.real_info())
            for info in (self.real_info() | {"commit": "b" * 40},):
                with self.assertRaisesRegex(RuntimeError, "verification failed"):
                    release.verify(archive, bundle, info)
            which.assert_not_called()
            run.assert_not_called()

    def test_unreadable_bundle_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            archive, bundle = Path(d) / "a", Path(d) / "b"
            archive.write_bytes(b"x")
            bundle.write_bytes(b"{not json")
            with patch.object(release.shutil, "which", return_value="/usr/bin/gh"), \
                    self.assertRaisesRegex(RuntimeError, "verification failed"):
                release.verify(archive, bundle, self.real_info())


if __name__ == "__main__":
    unittest.main()
