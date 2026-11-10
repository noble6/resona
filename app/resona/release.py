"""Fail-closed policy for source archives signed by Resona's release workflow."""
import hashlib
import json
import re
import shutil
import subprocess

REPO = "noble6/resona"
WORKFLOW = f"{REPO}/.github/workflows/release.yml"
MAX_METADATA_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 4 * 1024 * 1024


def version(tag):
    if not isinstance(tag, str) or not re.fullmatch(r"[vV]?\d+\.\d+\.\d+", tag):
        raise RuntimeError("Unexpected release tag")
    return tag.lstrip("vV")


def read_json(get, url):
    with get(url) as response:
        content = response.read(MAX_METADATA_BYTES + 1)
    if len(content) > MAX_METADATA_BYTES:
        raise RuntimeError("Release metadata exceeds the size limit")
    return json.loads(content)


def resolve_commit(get, tag):
    version(tag)
    data = read_json(get, f"https://api.github.com/repos/{REPO}/git/ref/tags/{tag}")
    for _ in range(6):
        obj = data.get("object", {}) if isinstance(data, dict) else {}
        sha, kind = obj.get("sha"), obj.get("type")
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise RuntimeError("Release tag does not resolve to a valid commit")
        if kind == "commit":
            return sha
        if kind != "tag":
            break
        data = read_json(get, f"https://api.github.com/repos/{REPO}/git/tags/{sha}")
    raise RuntimeError("Release tag does not resolve to a commit within the limit")


def urls(tag):
    version(tag)
    archive = f"https://github.com/{REPO}/releases/download/{tag}/resona-{tag}.tar.gz"
    return archive, archive + ".sigstore.json"


def update_files(get, metadata, tag):
    archive, bundle = urls(tag)
    assets = metadata.get("assets", [])
    if not isinstance(assets, list):
        raise RuntimeError("Invalid release assets")
    for url in (archive, bundle):
        matches = [asset for asset in assets if isinstance(asset, dict)
                   and asset.get("name") == url.rsplit("/", 1)[1]]
        if len(matches) != 1 or matches[0].get("browser_download_url") != url or matches[0].get("state") != "uploaded":
            raise RuntimeError("Release lacks attested update files; install manually or wait for release packaging")
    return dict(tarball=archive, attestation=bundle, commit=resolve_commit(get, tag))


def validate_info(info):
    tag = info.get("tag")
    if info.get("version") != version(tag):
        raise RuntimeError("Release tag and version do not match")
    commit = info.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise RuntimeError("Update is not pinned to a valid source commit")
    archive, bundle = urls(tag)
    if info.get("tarball") != archive or info.get("attestation") != bundle:
        raise RuntimeError("Unexpected download location")
    return archive


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_native(archive, bundle, info):
    """Built-in offline Sigstore verification. Returns False when it cannot judge the bundle."""
    try:
        from . import sigstore_verify
    except ImportError:          # python-cryptography missing
        return False
    try:
        with open(bundle, "rb") as stream:
            data = json.loads(stream.read(MAX_BUNDLE_BYTES + 1))
        sigstore_verify.verify_bundle(
            data, _sha256_file(archive), repo=REPO, workflow=WORKFLOW, tag=info["tag"],
            commit=info["commit"], subject_name=f"resona-{info['tag']}.tar.gz")
    except sigstore_verify.UnsupportedBundle:
        return False             # a newer bundle format: let gh decide if it is available
    except Exception as error:   # any other doubt refuses the update, never falls through
        raise RuntimeError("Update authenticity verification failed; installation refused") from error
    return True


def verify(archive, bundle, info):
    validate_info(info)
    if _verify_native(archive, bundle, info):
        return
    executable = shutil.which("gh")
    if not executable:
        raise RuntimeError("Could not verify this update here. Install python-cryptography (or the GitHub CLI), "
                           "or update Resona manually")
    command = [executable, "attestation", "verify", str(archive), "--bundle", str(bundle),
               "--hostname", "github.com", "--repo", REPO,
               "--cert-identity", f"https://github.com/{WORKFLOW}@refs/tags/{info['tag']}",
               "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
               "--source-ref", f"refs/tags/{info['tag']}", "--source-digest", info["commit"],
               "--predicate-type", "https://slsa.dev/provenance/v1", "--deny-self-hosted-runners"]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Could not verify update authenticity; installation refused") from error
    if result.returncode:
        raise RuntimeError("Update authenticity verification failed; installation refused. Use a current GitHub CLI")
