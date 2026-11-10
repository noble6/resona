"""Opt-in network/installation check using only a temporary prefix and private audio server."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from resona import release, updater


def run_python(code, arguments, env, payload=None):
    result = subprocess.run([sys.executable, "-c", code, *map(str, arguments)], env=env,
                            input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True, timeout=720)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    print(result.stdout.strip(), flush=True)


def release_info(tag):
    release.version(tag)
    metadata = release.read_json(updater._get, f"https://api.github.com/repos/{release.REPO}/releases/tags/{tag}")
    if metadata.get("tag_name") != tag or metadata.get("draft") or metadata.get("prerelease"):
        raise RuntimeError("Expected an exact stable published release")
    return dict(tag=tag, version=release.version(tag), **release.update_files(updater._get, metadata, tag))


def verify_download(info, directory, env):
    archive = directory / f"resona-{info['tag']}.tar.gz"
    bundle = directory / (archive.name + ".sigstore.json")
    updater._download(info["tarball"], archive)
    updater._download(info["attestation"], bundle, release.MAX_BUNDLE_BYTES)
    command = [shutil.which("gh"), "attestation", "verify", str(archive), "--bundle", str(bundle),
               "--hostname", "github.com", "--repo", release.REPO,
               "--cert-identity", f"https://github.com/{release.WORKFLOW}@refs/tags/{info['tag']}",
               "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
               "--source-ref", f"refs/tags/{info['tag']}", "--source-digest", info["commit"],
               "--deny-self-hosted-runners"]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise RuntimeError("Independent GitHub CLI verification failed: " + result.stderr)
    tampered = directory / (archive.name + ".tampered")
    content = bytearray(archive.read_bytes())
    content[-1] ^= 1
    tampered.write_bytes(content)
    run_python('''
import json, sys
from pathlib import Path
from resona import release
info = json.load(sys.stdin)
release.verify(Path(sys.argv[1]), Path(sys.argv[2]), info)
try:
    release.verify(Path(sys.argv[3]), Path(sys.argv[2]), info)
except RuntimeError:
    pass
else:
    raise AssertionError("tampered archive accepted")
print(info['tag'] + ': built-in verification passes without gh; tampered archive rejected')
''', [archive, bundle, tampered], dict(env, PATH="", PYTHONPATH=str(ROOT / "app")), info)
    print(f"{info['tag']}: independent gh verification passed; commit {info['commit']}", flush=True)
    return archive, bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-tag", required=True, help="Older stable release with attested source assets")
    parser.add_argument("--to-tag", help="Latest stable release (defaults to GitHub's latest release)")
    parser.add_argument("--with-ui", action="store_true", help="Also launch the upgraded app on private PipeWire")
    args = parser.parse_args()
    if shutil.which("gh") is None:
        parser.error("gh is required for independent signature verification and the v2.2.2 updater")
    latest = release.read_json(updater._get, updater.API)["tag_name"]
    target_tag = args.to_tag or latest
    if target_tag != latest:
        parser.error("--to-tag must be the latest release so the installed update check can be exercised")
    old, new = release_info(args.from_tag), release_info(target_tag)
    if updater.version_tuple(old["version"]) >= updater.version_tuple(new["version"]):
        parser.error("--from-tag must precede --to-tag")
    with tempfile.TemporaryDirectory(prefix="resona-release-upgrade-") as directory:
        root = Path(directory)
        prefix = root / "prefix"
        app = prefix / "share/resona"
        app.mkdir(parents=True)
        env = dict(os.environ)
        for name in ("CONFIG", "STATE", "CACHE", "DATA", "RUNTIME"):
            path = root / name.lower()
            path.mkdir(mode=0o700)
            env[f"XDG_{name}_HOME" if name != "RUNTIME" else "XDG_RUNTIME_DIR"] = str(path)
        os.environ.update({key: value for key, value in env.items() if key.startswith("XDG_")})
        state = root / "config/resona/state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps(dict(profile="Music", params={"bass_amt": 0.25}, update_freq="manual")))
        preset = state.parent / "presets/Keep.json"
        preset.parent.mkdir()
        preset.write_text(json.dumps(dict(resona_preset=1, params={"bass_amt": 0.25})))
        unrelated = prefix / "keep-unrelated"
        unrelated.write_text("keep")
        sentinels = {path: path.read_bytes() for path in (state, preset, unrelated)}
        verify_download(old, root, env)
        archive, bundle = verify_download(new, root, env)
        # Only the test prefix/cache change; verification, downloads, build and installer stay real.
        updater.APP_DIR = app
        updater.CACHE = root / "cache/fresh-install"
        assert updater.install_kind() == "user"
        launcher = updater.install(old)
        assert Path(launcher) == prefix / "bin/resona"
        print(old["tag"] + ': real fresh installation passed', flush=True)
        installed_env = dict(env, PYTHONPATH=str(app))
        run_python('''
import json, sys
from pathlib import Path
import resona
from resona import updater
expected = json.load(sys.stdin)
assert resona.__version__ == expected['from_version']
assert Path(resona.__file__).resolve().is_relative_to(Path(sys.argv[1]))
assert updater.install_kind() == 'user'
info = updater.check()
assert info['available'] and info['tag'] == expected['tag'] and info['commit'] == expected['commit'], 'release changed during test'
updater.install(info)
print('Installed old updater downloaded, verified, built, and installed ' + info['tag'])
''', [app], installed_env, dict(new, from_version=old["version"]))
        run_python('''
import json, sys
from pathlib import Path
import resona
from resona import persistence, release, updater
info = json.load(sys.stdin)
assert resona.__version__ == info['version']
assert Path(resona.__file__).resolve().is_relative_to(Path(sys.argv[1]))
assert updater.install_kind() == 'user'
assert persistence.load_state()['params']['bass_amt'] == 0.25
release.verify(Path(sys.argv[2]), Path(sys.argv[3]), info)
print('Upgraded installed copy reports ' + resona.__version__ + '; native verification passes without gh')
''', [app, archive, bundle], dict(installed_env, PATH=""), new)
        for path, content in sentinels.items():
            assert path.read_bytes() == content, f"installation changed {path.name}"
        assert not (prefix / ".resona-install.json").exists()
        assert not list(prefix.rglob(".resona-install-*"))
        if args.with_ui:
            result = subprocess.run(["bash", str(ROOT / "tests/run_pipewire.sh")], cwd=ROOT,
                                    env=dict(installed_env, RESONA_TEST_APP=str(app / "main.py"),
                                             RESONA_PLUGIN=str(prefix / "lib/resona/resona.so")),
                                    capture_output=True, text=True, timeout=240)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            print("Upgraded installed app passed private PipeWire/UI smoke tests", flush=True)
        print("PASS: real release upgrade verified; settings/presets preserved; user installation untouched", flush=True)


if __name__ == "__main__":
    main()
