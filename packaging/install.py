"""Stage an installation and restore previous artifacts if publication fails."""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona.desktop import exec_line

JOURNAL = ".resona-install.json"
ARTIFACTS = {
    "lib/resona/resona.so", "share/resona", "bin/resona",
    "share/icons/hicolor/scalable/apps/resona.svg", "share/applications/resona.desktop",
}


def sync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sync_tree(path: Path) -> None:
    if path.is_dir():
        for child in path.iterdir():
            sync_tree(child)
        sync_dir(path)
    else:
        with path.open("rb") as stream:
            os.fsync(stream.fileno())


def journal(prefix: Path, phase: str, entries: list) -> None:
    data = dict(version=1, phase=phase, entries=[
        [str(target.relative_to(prefix)), str(workspace.relative_to(prefix)), original]
        for target, workspace, original in entries
    ])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".resona-journal-", dir=prefix,
                                         delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, prefix / JOURNAL)
        sync_dir(prefix)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def clean(prefix: Path, entries: list) -> None:
    for _, workspace, _ in entries:
        if workspace.exists():
            shutil.rmtree(workspace)
            sync_dir(workspace.parent)
    (prefix / JOURNAL).unlink(missing_ok=True)
    sync_dir(prefix)


def recover(prefix: Path) -> None:
    path = prefix / JOURNAL
    if not os.path.lexists(path):
        return
    if path.is_symlink():
        raise RuntimeError("Refusing a symlinked installation journal")
    with path.open("rb") as stream:
        content = stream.read(65537)
    if len(content) > 65536:
        raise RuntimeError("Installation journal exceeds the size limit")
    data = json.loads(content)
    if not isinstance(data, dict) or data.get("version") != 1 or data.get("phase") not in ("staging", "prepared", "committed"):
        raise RuntimeError("Invalid installation journal; preserve files for manual recovery")
    records = data.get("entries")
    if not isinstance(records, list) or len(records) > len(ARTIFACTS):
        raise RuntimeError("Invalid installation journal entries")
    if data["phase"] != "staging" and len(records) != len(ARTIFACTS):
        raise RuntimeError("Incomplete installation journal")
    entries, seen = [], set()
    for record in records:
        if not isinstance(record, list) or len(record) != 3:
            raise RuntimeError("Invalid installation journal entry")
        target, workspace, original = record
        if not isinstance(target, str) or target not in ARTIFACTS or target in seen or not isinstance(original, bool):
            raise RuntimeError("Invalid installation journal target")
        if not isinstance(workspace, str):
            raise RuntimeError("Invalid recovery workspace")
        relative = Path(workspace)
        destination = prefix / target
        location = prefix / relative
        if relative.is_absolute() or ".." in relative.parts or location.parent != destination.parent or not location.name.startswith(".resona-install-") or location.is_symlink():
            raise RuntimeError("Unsafe recovery workspace; preserve files for manual recovery")
        if data["phase"] == "prepared" and not location.is_dir():
            raise RuntimeError("Missing recovery workspace; preserve files for manual recovery")
        seen.add(target)
        entries.append((destination, location, original))
    if data["phase"] == "prepared":
        rollback(entries)
        journal(prefix, "staging", entries)
    clean(prefix, entries)


def remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def stage(source: Path, prefix: Path, entries: list) -> None:
    launcher = (
        "#!/bin/sh\n"
        "export RESONA_PLUGIN=" + shlex.quote(str(prefix / "lib/resona/resona.so")) + "\n"
        "exec python3 " + shlex.quote(str(prefix / "share/resona/main.py")) + ' "$@"\n'
    )
    desktop = (
        "[Desktop Entry]\nType=Application\nName=Resona\nGenericName=Sound Enhancer\n"
        "Comment=Spatial sound, DeepBass, smart EQ and loudness for PipeWire\n"
        f"Exec={exec_line([str(prefix / 'bin/resona')])}\n"
        "Icon=resona\nCategories=AudioVideo;Audio;Mixer;\n"
        "Keywords=equalizer;eq;bass;dolby;dts;surround;spatial;audio;effects;pipewire;\n"
        "StartupWMClass=resona\n"
    )
    for relative, payload, mode in (
        ("lib/resona/resona.so", source / "engine/resona.so", 0o755),
        ("share/resona", None, 0o755),
        ("bin/resona", launcher, 0o755),
        ("share/icons/hicolor/scalable/apps/resona.svg", source / "app/icons/resona.svg", 0o644),
        ("share/applications/resona.desktop", desktop, 0o644),
    ):
        destination = prefix / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Sibling workspaces keep renames on the destination filesystem.
        workspace = Path(tempfile.mkdtemp(prefix=".resona-install-", dir=destination.parent))
        entries.append((destination, workspace, os.path.lexists(destination)))
        journal(prefix, "staging", entries)
        new = workspace / "new"
        if payload is None:
            new.mkdir(mode=mode)
            for name in ("main.py", "resona", "qml", "fonts", "icons"):
                item = source / "app" / name
                if item.is_dir():
                    shutil.copytree(item, new / name, ignore=shutil.ignore_patterns("__pycache__"))
                else:
                    shutil.copy2(item, new / name)
        elif isinstance(payload, Path):
            shutil.copyfile(payload, new)
        else:
            new.write_text(payload, encoding="utf-8")
        new.chmod(mode)
        sync_tree(new)
        sync_dir(workspace)
        parent = destination.parent
        while parent.is_relative_to(prefix):
            sync_dir(parent)
            if parent == prefix:
                break
            parent = parent.parent


def publish(entries: list) -> None:
    for destination, workspace, _ in entries:
        if os.path.lexists(destination):
            os.replace(destination, workspace / "previous")
            sync_dir(workspace)
            sync_dir(destination.parent)
        os.replace(workspace / "new", destination)
        sync_dir(workspace)
        sync_dir(destination.parent)


def rollback(entries: list) -> None:
    failures = []
    for destination, workspace, original in reversed(entries):
        try:
            if os.path.lexists(workspace / "previous"):
                remove(destination)
                os.replace(workspace / "previous", destination)
            elif not original and not os.path.lexists(workspace / "new"):
                remove(destination)
            elif original and not os.path.lexists(destination):
                raise OSError("original artifact and backup are both missing")
            sync_dir(workspace)
            sync_dir(destination.parent)
        except OSError as error:
            failures.append(f"{destination}: {error}; backup workspace: {workspace}")
    if failures:
        raise RuntimeError("Rollback incomplete; preserve recovery files: " + "; ".join(failures))


@contextmanager
def prefix_lock(prefix: Path):
    descriptor = os.open(prefix, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def install(source: Path, prefix: Path) -> None:
    prefix = Path(os.path.abspath(prefix))
    prefix.mkdir(parents=True, exist_ok=True)
    # Lock the prefix directory without leaving a lock file in the installation.
    with prefix_lock(prefix):
        recover(prefix)
        entries = []
        publishing = False
        committing = False
        preserve = False
        old_mask = None
        try:
            stage(source, prefix, entries)
            journal(prefix, "prepared", entries)
            publishing = True
            publish(entries)
            committing = True
            journal(prefix, "committed", entries)
        except BaseException:
            # A second catchable signal must not interrupt recovery.
            old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
            if committing:
                preserve = True
            elif publishing:
                try:
                    rollback(entries)
                    journal(prefix, "staging", entries)
                except BaseException:
                    preserve = True
                    raise
            raise
        finally:
            if old_mask is None:
                old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
            try:
                if not preserve:
                    clean(prefix, entries)
            finally:
                signal.pthread_sigmask(signal.SIG_SETMASK, old_mask)


def interrupted(signum, frame):
    raise InterruptedError(f"Installation interrupted by signal {signum}")


def main() -> None:
    prefix = Path(sys.argv[1]).absolute()
    install(Path(__file__).resolve().parents[1], prefix)
    try:
        subprocess.run(["update-desktop-database", "-q", str(prefix / "share/applications")],
                       check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass
    print(f"Resona installed to {prefix}. Launch it from your app menu or run: resona")


if __name__ == "__main__":
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        main()
    except Exception as error:
        print(f"Install failed: {error}", file=sys.stderr)
        sys.exit(1)
