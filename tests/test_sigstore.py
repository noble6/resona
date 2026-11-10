"""Native Sigstore verification against the real v2.2.2 release bundle, plus tampering at every layer."""
import base64
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from resona import sigstore_verify as sv  # noqa: E402

BUNDLE = json.loads((ROOT / "tests/fixtures/resona-v2.2.2.tar.gz.sigstore.json").read_text())
DIGEST = "2ded033118313062773369f179c45bc941441ee6bfcb6d32f08c62835868afac"
GOOD = dict(repo="noble6/resona", workflow="noble6/resona/.github/workflows/release.yml",
            tag="v2.2.2", commit="97876d9147746d2fb20c0eb68fb9869a5e94362f",
            subject_name="resona-v2.2.2.tar.gz")


def flip(text: str, at: int = 10) -> str:
    raw = bytearray(base64.b64decode(text))
    raw[at % len(raw)] ^= 1
    return base64.b64encode(bytes(raw)).decode()


class Native(unittest.TestCase):
    def verify(self, bundle=None, digest=DIGEST, root=None, **overrides):
        sv.verify_bundle(bundle or BUNDLE, digest, root=root, **{**GOOD, **overrides})

    def rejects(self, message, **kw):
        with self.assertRaisesRegex(sv.VerificationError, message):
            self.verify(**kw)

    def entry(self, bundle):
        return bundle["verificationMaterial"]["tlogEntries"][0]

    def test_genuine_release_verifies(self):
        self.verify()

    def test_wrong_archive(self):
        self.rejects("does not match the signed release", digest="0" * 64)

    def test_wrong_tag_commit_repo_workflow(self):
        self.rejects("release workflow for this tag", tag="v2.2.1")
        self.rejects("identity does not match", commit="1" * 40)
        self.rejects("release workflow for this tag", workflow="noble6/resona/.github/workflows/ci.yml")
        self.rejects("release workflow for this tag", repo="someone/resona",
                     workflow="someone/resona/.github/workflows/release.yml")

    def test_wrong_subject_name(self):
        self.rejects("different artifact", subject_name="other.tar.gz")

    def test_tampered_signed_entry_timestamp(self):
        b = copy.deepcopy(BUNDLE)
        e = self.entry(b)
        e["inclusionPromise"]["signedEntryTimestamp"] = flip(e["inclusionPromise"]["signedEntryTimestamp"], 20)
        self.rejects("Invalid transparency-log timestamp signature", bundle=b)

    def test_shifted_integrated_time(self):
        b = copy.deepcopy(BUNDLE)
        self.entry(b)["integratedTime"] = str(int(self.entry(b)["integratedTime"]) + 60)
        self.rejects("transparency-log timestamp", bundle=b)

    def test_tampered_inclusion_proof(self):
        for field in ("hashes", "rootHash"):
            b = copy.deepcopy(BUNDLE)
            proof = self.entry(b)["inclusionProof"]
            if field == "hashes":
                proof["hashes"][0] = flip(proof["hashes"][0])
            else:
                proof["rootHash"] = flip(proof["rootHash"])
            self.rejects("inclusion proof does not verify", bundle=b)

    def test_tampered_checkpoint_signature(self):
        b = copy.deepcopy(BUNDLE)
        cp = self.entry(b)["inclusionProof"]["checkpoint"]
        body, sig = cp["envelope"].split("\n\n", 1)
        dash, name, value = sig.strip().split(" ")
        cp["envelope"] = body + "\n\n" + " ".join([dash, name, flip(value, 30)]) + "\n"
        self.rejects("checkpoint", bundle=b)

    def test_logged_entry_must_match_envelope(self):
        b = copy.deepcopy(BUNDLE)
        b["dsseEnvelope"]["signatures"][0]["sig"] = flip(b["dsseEnvelope"]["signatures"][0]["sig"], 40)
        self.rejects("different signature", bundle=b)
        b = copy.deepcopy(BUNDLE)
        statement = json.loads(base64.b64decode(b["dsseEnvelope"]["payload"]))
        statement["subject"][0]["digest"]["sha256"] = "0" * 64
        b["dsseEnvelope"]["payload"] = base64.b64encode(json.dumps(statement).encode()).decode()
        self.rejects("different payload", bundle=b, digest="0" * 64)

    def test_release_signature_checked(self):
        # bypass the log so the DSSE signature check itself is exercised
        b = copy.deepcopy(BUNDLE)
        b["dsseEnvelope"]["signatures"][0]["sig"] = flip(b["dsseEnvelope"]["signatures"][0]["sig"], 40)
        when = sv.datetime.fromtimestamp(int(self.entry(BUNDLE)["integratedTime"]), tz=sv.timezone.utc)
        with mock.patch.object(sv, "_verify_tlog", return_value=when):
            self.rejects("Invalid release signature", bundle=b)

    def test_untrusted_ca_and_ct_log(self):
        root = sv.TrustedRoot()
        no_ca = copy.copy(root); no_ca.cas = []
        self.rejects("does not chain to the Sigstore CA", root=no_ca)
        no_ct = copy.copy(root); no_ct.ctlogs = {}
        self.rejects("certificate-transparency", root=no_ct)

    def test_tampered_certificate(self):
        b = copy.deepcopy(BUNDLE)
        cert = b["verificationMaterial"]["certificate"]
        raw = bytearray(base64.b64decode(cert["rawBytes"]))
        raw[-20] ^= 1  # inside the CA signature
        cert["rawBytes"] = base64.b64encode(bytes(raw)).decode()
        with self.assertRaises((sv.VerificationError, ValueError)):
            self.verify(bundle=b)

    def test_unknown_formats_are_unsupported_not_valid(self):
        b = copy.deepcopy(BUNDLE); b["mediaType"] = "application/vnd.dev.sigstore.bundle.v0.4+json"
        with self.assertRaises(sv.UnsupportedBundle):
            self.verify(bundle=b)
        b = copy.deepcopy(BUNDLE); self.entry(b)["kindVersion"]["version"] = "0.0.2"
        with self.assertRaises(sv.UnsupportedBundle):
            self.verify(bundle=b)
        b = copy.deepcopy(BUNDLE); self.entry(b)["logId"]["keyId"] = base64.b64encode(b"x" * 32).decode()
        with self.assertRaises(sv.UnsupportedBundle):
            self.verify(bundle=b)


class Merkle(unittest.TestCase):
    def test_every_leaf_of_every_small_tree(self):
        h = lambda b: hashlib.sha256(b).digest()  # noqa: E731

        def mth(leaves):
            if len(leaves) == 1:
                return h(b"\x00" + leaves[0])
            k = 1
            while k * 2 < len(leaves):
                k *= 2
            return h(b"\x01" + mth(leaves[:k]) + mth(leaves[k:]))

        def path(m, leaves):
            if len(leaves) == 1:
                return []
            k = 1
            while k * 2 < len(leaves):
                k *= 2
            if m < k:
                return path(m, leaves[:k]) + [mth(leaves[k:])]
            return path(m - k, leaves[k:]) + [mth(leaves[:k])]

        for n in range(1, 18):
            leaves = [bytes([i]) * 3 for i in range(n)]
            root = mth(leaves)
            for m in range(n):
                proof = path(m, leaves)
                self.assertEqual(sv._merkle_root(m, n, h(b"\x00" + leaves[m]), proof), root)
                if proof:
                    with self.assertRaises(sv.VerificationError):
                        sv._merkle_root(m, n, h(b"\x00" + leaves[m]), proof[:-1])
                    bad = [bytes(32)] + proof[1:]
                    self.assertNotEqual(sv._merkle_root(m, n, h(b"\x00" + leaves[m]), bad), root)


if __name__ == "__main__":
    unittest.main()
