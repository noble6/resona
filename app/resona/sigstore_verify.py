"""Offline verification of Sigstore bundles from GitHub's attest-build-provenance.

Checks what `gh attestation verify` checks for Resona releases, without needing gh:
the signing certificate chains to Sigstore's Fulcio CA and carries a valid embedded
certificate-transparency timestamp; its identity is Resona's release workflow at the
expected tag, commit and a GitHub-hosted runner; the DSSE signature covers an in-toto
SLSA provenance statement whose only subject is the archive's SHA-256; and the Rekor
transparency-log entry matches the envelope, with a valid signed entry timestamp,
Merkle inclusion proof and signed checkpoint. Trust anchors come from the vendored
Sigstore public-good trusted root (data/sigstore_trusted_root.json).

Anything unexpected raises; nothing falls through to "valid".
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID

TRUSTED_ROOT = Path(__file__).resolve().parent / "data" / "sigstore_trusted_root.json"
BUNDLE_MEDIA_TYPES = {"application/vnd.dev.sigstore.bundle.v0.3+json"}
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
PAYLOAD_TYPE = "application/vnd.in-toto+json"
STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"

# Fulcio certificate extensions (DER UTF8String values)
OID_ISSUER_V2 = x509.ObjectIdentifier("1.3.6.1.4.1.57264.1.8")
OID_RUNNER_ENV = x509.ObjectIdentifier("1.3.6.1.4.1.57264.1.11")
OID_SOURCE_REPO_URI = x509.ObjectIdentifier("1.3.6.1.4.1.57264.1.12")
OID_SOURCE_REPO_DIGEST = x509.ObjectIdentifier("1.3.6.1.4.1.57264.1.13")
OID_SOURCE_REPO_REF = x509.ObjectIdentifier("1.3.6.1.4.1.57264.1.14")


class VerificationError(RuntimeError):
    """The bundle is well-formed but does not prove what it must."""


class UnsupportedBundle(RuntimeError):
    """The bundle uses a format this verifier does not implement."""


def _b64(value) -> bytes:
    if not isinstance(value, str):
        raise VerificationError("Expected base64 text in bundle")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as error:
        raise VerificationError("Invalid base64 in bundle") from error


def _time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _valid_at(window: dict, when: datetime) -> bool:
    start = _time(window["start"]) if window.get("start") else None
    end = _time(window["end"]) if window.get("end") else None
    return (start is None or start <= when) and (end is None or when <= end)


def _ecdsa_key(raw: bytes):
    key = serialization.load_der_public_key(raw)
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise UnsupportedBundle("Unsupported transparency log key type")
    return key


def _verify_ecdsa(key, signature: bytes, data: bytes, what: str) -> None:
    try:
        key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as error:
        raise VerificationError(f"Invalid {what} signature") from error


def _utf8_ext(cert: x509.Certificate, oid) -> str:
    try:
        raw = cert.extensions.get_extension_for_oid(oid).value.value
    except x509.ExtensionNotFound as error:
        raise VerificationError("Signing certificate lacks a required identity field") from error
    # DER UTF8String: tag 0x0c, definite length (short or long form)
    if len(raw) < 2 or raw[0] != 0x0C:
        raise VerificationError("Malformed identity field in signing certificate")
    length, offset = raw[1], 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 2 or len(raw) < 2 + count:
            raise VerificationError("Malformed identity field in signing certificate")
        length, offset = int.from_bytes(raw[2:2 + count], "big"), 2 + count
    if offset + length != len(raw):
        raise VerificationError("Malformed identity field in signing certificate")
    return raw[offset:].decode("utf-8")


class TrustedRoot:
    def __init__(self, path: Path = TRUSTED_ROOT):
        data = json.loads(path.read_text())
        self.tlogs = {}
        for log in data.get("tlogs", []):
            if log["publicKey"].get("keyDetails") == "PKIX_ECDSA_P256_SHA_256":
                self.tlogs[_b64(log["logId"]["keyId"])] = (_b64(log["publicKey"]["rawBytes"]),
                                                           log["publicKey"].get("validFor", {}))
        self.ctlogs = {}
        for log in data.get("ctlogs", []):
            if log["publicKey"].get("keyDetails") == "PKIX_ECDSA_P256_SHA_256":
                self.ctlogs[_b64(log["logId"]["keyId"])] = (_b64(log["publicKey"]["rawBytes"]),
                                                            log["publicKey"].get("validFor", {}))
        self.cas = []
        for ca in data.get("certificateAuthorities", []):
            chain = [x509.load_der_x509_certificate(_b64(c["rawBytes"])) for c in ca["certChain"]["certificates"]]
            self.cas.append((chain, ca.get("validFor", {})))


def _verify_chain(leaf: x509.Certificate, root: TrustedRoot, when: datetime) -> x509.Certificate:
    """Return the issuing intermediate once leaf -> ... -> self-signed anchor checks out."""
    for chain, window in root.cas:
        if not chain or not _valid_at(window, when):
            continue
        path = [leaf, *chain]
        try:
            for child, parent in zip(path, path[1:]):
                child.verify_directly_issued_by(parent)
            path[-1].verify_directly_issued_by(path[-1])
        except (ValueError, TypeError, InvalidSignature):
            continue
        for cert in path:
            if not cert.not_valid_before_utc <= when <= cert.not_valid_after_utc:
                raise VerificationError("Certificate was not valid when the release was signed")
        for ca_cert in chain:
            bc = ca_cert.extensions.get_extension_for_class(x509.BasicConstraints).value
            if not bc.ca:
                raise VerificationError("Certificate chain contains a non-CA issuer")
        return chain[0]
    raise VerificationError("Signing certificate does not chain to the Sigstore CA")


def _verify_sct(leaf: x509.Certificate, issuer: x509.Certificate, root: TrustedRoot) -> None:
    try:
        scts = leaf.extensions.get_extension_for_class(x509.PrecertificateSignedCertificateTimestamps).value
    except x509.ExtensionNotFound as error:
        raise VerificationError("Signing certificate has no certificate-transparency timestamp") from error
    issuer_key_hash = hashlib.sha256(issuer.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).digest()
    tbs = leaf.tbs_precertificate_bytes
    for sct in scts:
        known = root.ctlogs.get(sct.log_id)
        if not known:
            continue
        stamp = round(sct.timestamp.replace(tzinfo=timezone.utc).timestamp() * 1000)
        ext = sct.extension_bytes
        signed = (struct.pack(">BBQH", 0, 0, stamp, 1) + issuer_key_hash
                  + len(tbs).to_bytes(3, "big") + tbs + len(ext).to_bytes(2, "big") + ext)
        _verify_ecdsa(_ecdsa_key(known[0]), sct.signature, signed, "certificate-transparency")
        return
    raise VerificationError("No certificate-transparency timestamp from a trusted log")


def _verify_identity(leaf: x509.Certificate, repo: str, workflow: str, tag: str, commit: str) -> None:
    eku = leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    if ExtendedKeyUsageOID.CODE_SIGNING not in eku:
        raise VerificationError("Signing certificate is not for code signing")
    san = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    uris = san.get_values_for_type(x509.UniformResourceIdentifier)
    expected = f"https://github.com/{workflow}@refs/tags/{tag}"
    if uris != [expected]:
        raise VerificationError("Release was not signed by Resona's release workflow for this tag")
    checks = {
        OID_ISSUER_V2: OIDC_ISSUER,
        OID_SOURCE_REPO_URI: f"https://github.com/{repo}",
        OID_SOURCE_REPO_DIGEST: commit,
        OID_SOURCE_REPO_REF: f"refs/tags/{tag}",
        OID_RUNNER_ENV: "github-hosted",
    }
    for oid, value in checks.items():
        if _utf8_ext(leaf, oid) != value:
            raise VerificationError("Signing certificate identity does not match the release")


def _merkle_root(index: int, size: int, leaf: bytes, proof: list[bytes]) -> bytes:
    """RFC 9162 section 2.1.3.2 inclusion-proof verification."""
    if not 0 <= index < size:
        raise VerificationError("Inclusion proof index out of range")
    fn, sn, r = index, size - 1, leaf
    for p in proof:
        if sn == 0:
            raise VerificationError("Inclusion proof is too long")
        if fn & 1 or fn == sn:
            r = hashlib.sha256(b"\x01" + p + r).digest()
            if not fn & 1:
                while fn and not fn & 1:
                    fn >>= 1
                    sn >>= 1
        else:
            r = hashlib.sha256(b"\x01" + r + p).digest()
        fn >>= 1
        sn >>= 1
    if sn != 0:
        raise VerificationError("Inclusion proof is too short")
    return r


def _verify_checkpoint(envelope: str, key, key_id: bytes, size: int, root_hash: bytes) -> None:
    if "\n\n" not in envelope:
        raise VerificationError("Malformed transparency-log checkpoint")
    body, signatures = envelope.split("\n\n", 1)
    body += "\n"
    lines = body.split("\n")
    if len(lines) < 4 or lines[1] != str(size) or _b64(lines[2]) != root_hash:
        raise VerificationError("Checkpoint does not match the inclusion proof")
    for line in signatures.strip().split("\n"):
        parts = line.split(" ")
        if len(parts) != 3 or parts[0] != "—":
            continue
        raw = _b64(parts[2])
        if raw[:4] == key_id[:4]:
            _verify_ecdsa(key, raw[4:], body.encode(), "transparency-log checkpoint")
            return
    raise VerificationError("Checkpoint is not signed by the transparency log")


def _verify_tlog(entry: dict, root: TrustedRoot, envelope: dict, signature: bytes, leaf_pem: bytes) -> datetime:
    if entry.get("kindVersion") != {"kind": "dsse", "version": "0.0.1"}:
        raise UnsupportedBundle("Unsupported transparency-log entry type")
    key_id = _b64(entry.get("logId", {}).get("keyId"))
    known = root.tlogs.get(key_id)
    if not known:
        raise UnsupportedBundle("Bundle uses an unknown transparency log")
    key = _ecdsa_key(known[0])
    body_raw = _b64(entry.get("canonicalizedBody"))
    integrated, index = int(entry["integratedTime"]), int(entry["logIndex"])
    when = datetime.fromtimestamp(integrated, tz=timezone.utc)
    if not _valid_at(known[1], when):
        raise VerificationError("Transparency log key was not valid at signing time")

    # the logged entry must describe exactly this envelope
    body = json.loads(body_raw)
    spec = body.get("spec", {}) if isinstance(body, dict) else {}
    if body.get("kind") != "dsse" or body.get("apiVersion") != "0.0.1":
        raise VerificationError("Transparency-log entry has the wrong type")
    payload = _b64(envelope["payload"])
    if spec.get("payloadHash") != {"algorithm": "sha256", "value": hashlib.sha256(payload).hexdigest()}:
        raise VerificationError("Transparency-log entry is for a different payload")
    logged = spec.get("signatures")
    if (not isinstance(logged, list) or len(logged) != 1 or _b64(logged[0].get("signature")) != signature
            or _b64(logged[0].get("verifier")) != leaf_pem):
        raise VerificationError("Transparency-log entry is for a different signature")

    # signed entry timestamp: Rekor's promise of inclusion at integratedTime
    promise = _b64(entry.get("inclusionPromise", {}).get("signedEntryTimestamp"))
    canonical = json.dumps({"body": entry["canonicalizedBody"], "integratedTime": integrated,
                            "logID": key_id.hex(), "logIndex": index},
                           sort_keys=True, separators=(",", ":")).encode()
    _verify_ecdsa(key, promise, canonical, "transparency-log timestamp")

    # inclusion proof and its signed checkpoint
    proof = entry.get("inclusionProof")
    if not isinstance(proof, dict):
        raise VerificationError("Missing transparency-log inclusion proof")
    size, root_hash = int(proof["treeSize"]), _b64(proof["rootHash"])
    leaf_hash = hashlib.sha256(b"\x00" + body_raw).digest()
    if _merkle_root(int(proof["logIndex"]), size, leaf_hash, [_b64(h) for h in proof.get("hashes", [])]) != root_hash:
        raise VerificationError("Transparency-log inclusion proof does not verify")
    _verify_checkpoint(proof.get("checkpoint", {}).get("envelope", ""), key, key_id, size, root_hash)
    return when


def verify_bundle(bundle: dict, sha256_hex: str, *, repo: str, workflow: str, tag: str, commit: str,
                  subject_name: str | None = None, root: TrustedRoot | None = None) -> None:
    """Raise unless `bundle` proves Resona's release workflow attested an artifact with this digest."""
    root = root or TrustedRoot()
    if not isinstance(bundle, dict) or bundle.get("mediaType") not in BUNDLE_MEDIA_TYPES:
        raise UnsupportedBundle("Unsupported Sigstore bundle version")
    material = bundle.get("verificationMaterial", {})
    entries = material.get("tlogEntries")
    envelope = bundle.get("dsseEnvelope")
    if not isinstance(entries, list) or len(entries) != 1 or not isinstance(envelope, dict):
        raise UnsupportedBundle("Unsupported Sigstore bundle layout")
    if "certificate" not in material:
        raise UnsupportedBundle("Bundle does not carry a signing certificate")
    leaf = x509.load_der_x509_certificate(_b64(material["certificate"].get("rawBytes")))
    leaf_pem = leaf.public_bytes(serialization.Encoding.PEM)

    sigs = envelope.get("signatures")
    if envelope.get("payloadType") != PAYLOAD_TYPE or not isinstance(sigs, list) or len(sigs) != 1:
        raise VerificationError("Unexpected signed envelope")
    signature = _b64(sigs[0].get("sig"))

    when = _verify_tlog(entries[0], root, envelope, signature, leaf_pem)
    issuer = _verify_chain(leaf, root, when)
    _verify_sct(leaf, issuer, root)
    _verify_identity(leaf, repo, workflow, tag, commit)

    payload = _b64(envelope["payload"])
    pae = b"DSSEv1 %d %s %d %s" % (len(PAYLOAD_TYPE), PAYLOAD_TYPE.encode(), len(payload), payload)
    key = leaf.public_key()
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise UnsupportedBundle("Unsupported signing key type")
    _verify_ecdsa(key, signature, pae, "release")

    statement = json.loads(payload)
    if statement.get("_type") != STATEMENT_TYPE or statement.get("predicateType") != PREDICATE_TYPE:
        raise VerificationError("Attestation is not SLSA build provenance")
    subjects = statement.get("subject")
    if not isinstance(subjects, list) or len(subjects) != 1:
        raise VerificationError("Attestation must cover exactly one artifact")
    if subjects[0].get("digest", {}).get("sha256") != sha256_hex.lower():
        raise VerificationError("Downloaded archive does not match the signed release")
    if subject_name is not None and subjects[0].get("name") != subject_name:
        raise VerificationError("Attestation names a different artifact")
