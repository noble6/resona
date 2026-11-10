"""Self-update from GitHub releases (only the noble6/resona repository, only release tags)."""
from __future__ import annotations

import json
import gzip
import os
import re
import shlex
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath

from . import __version__

REPO = "noble6/resona"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "resona" / "update"
APP_DIR = Path(__file__).resolve().parent.parent          # .../share/resona or <repo>/app
FREQ_DAYS = {"manual": 0, "weekly": 7, "monthly": 30}
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 20000


def version_tuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)


def install_kind() -> str:
    """'user' (install.sh into a writable prefix), 'source' (git checkout) or 'system' (package manager)."""
    if (APP_DIR.parent / ".git").exists() or (APP_DIR.parent / "engine").is_dir():
        return "source"
    prefix = APP_DIR.parent.parent
    if APP_DIR.parent.name == "share" and os.access(prefix, os.W_OK) and os.access(APP_DIR, os.W_OK):
        return "user"
    return "system"


def _get(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={"User-Agent": f"Resona/{__version__}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def check() -> dict:
    """Latest release info. Raises on network errors."""
    try:
        with _get(API) as r:
            rel = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"available": False, "version": __version__, "notes": "", "tag": ""}
        raise
    tag = rel.get("tag_name", "")
    latest = tag.lstrip("vV")
    return {
        "available": version_tuple(latest) > version_tuple(__version__),
        "version": latest, "tag": tag,
        "title": rel.get("name") or tag,
        "notes": (rel.get("body") or "").strip(),
        "url": rel.get("html_url", f"https://github.com/{REPO}/releases"),
        "tarball": rel.get("tarball_url", ""),
    }


def _copy_limited(source, destination, limit: int, message: str) -> int:
    total = 0
    while chunk := source.read(min(65536, limit - total + 1)):
        total += len(chunk)
        if total > limit:
            raise RuntimeError(message)
        destination.write(chunk)
    return total


def _download(url: str, destination: Path) -> None:
    with _get(url, timeout=60) as response:
        length = getattr(response, "headers", {}).get("Content-Length")
        if length is not None:
            try:
                length = int(length)
            except ValueError as e:
                raise RuntimeError("Invalid update download length") from e
            if length < 0 or length > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("Update download exceeds the size limit")
        with destination.open("wb") as output:
            total = _copy_limited(response, output, MAX_DOWNLOAD_BYTES,
                                  "Update download exceeds the size limit")
        if length is not None and total != length:
            raise RuntimeError("Update download is incomplete")


def _extract(archive: Path, destination: Path) -> None:
    # Bound decompression before tarfile parses even large PAX metadata records.
    with tempfile.TemporaryFile(dir=archive.parent) as unpacked:
        with gzip.open(archive, "rb") as compressed:
            _copy_limited(compressed, unpacked, MAX_EXTRACTED_BYTES,
                          "Release archive exceeds the extraction limit")
        unpacked.seek(0)
        with tarfile.open(fileobj=unpacked, mode="r:") as source:
            members, total = [], 0
            for member in source:
                path = PurePosixPath(member.name)
                if not path.parts or path.is_absolute() or ".." in path.parts:
                    raise RuntimeError("Unsafe path in release archive")
                if not (member.isfile() or member.isdir()):
                    raise RuntimeError("Release archive contains links or special files")
                if member.size < 0:
                    raise RuntimeError("Invalid file size in release archive")
                total += member.size
                if total > MAX_EXTRACTED_BYTES or len(members) >= MAX_ARCHIVE_MEMBERS:
                    raise RuntimeError("Release archive exceeds the extraction limit")
                members.append(member)
            if not members:
                raise RuntimeError("Release archive is empty")
            source.extractall(destination, members=members, filter="data")


def install(info: dict) -> str:
    """Download the release source, build it and install over the running copy. Returns the launcher path."""
    kind = install_kind()
    if kind != "user":
        raise RuntimeError("Running from a git checkout: update with git pull" if kind == "source"
                           else "Installed by your package manager: update Resona with it")
    url = info.get("tarball", "")
    if not url.startswith(f"https://api.github.com/repos/{REPO}/"):
        raise RuntimeError("Unexpected download location")
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="release-", dir=CACHE) as directory:
        workspace = Path(directory)
        archive = workspace / "release.tar.gz"
        _download(url, archive)
        src = workspace / "src"
        _extract(archive, src)
        roots = [p for p in src.iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "install.sh").is_file():
            raise RuntimeError("Release archive has an unexpected layout")
        prefix = APP_DIR.parent.parent
        env = dict(os.environ, PREFIX=str(prefix))
        r = subprocess.run(["sh", str(roots[0] / "install.sh")], cwd=roots[0], env=env,
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            tail = (r.stderr or r.stdout).strip().splitlines()[-3:]
            raise RuntimeError("Install failed: " + " ".join(tail))
    return str(prefix / "bin" / "resona")


def relaunch(launcher: str, hidden: bool):
    """Start the new version once this process has exited (single-instance lock is released on quit)."""
    args = shlex.quote(launcher) + (" --hidden" if hidden else "")
    subprocess.Popen(["setsid", "-f", "sh", "-c", f"sleep 2; exec {args}"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
