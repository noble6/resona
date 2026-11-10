"""Stage an installation and restore previous artifacts if publication fails."""
from __future__ import annotations

import fcntl
from contextlib import contextmanager
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
        entries.append((destination, workspace))
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


def publish(entries: list) -> None:
    for destination, workspace in entries:
        if os.path.lexists(destination):
            os.replace(destination, workspace / "previous")
        os.replace(workspace / "new", destination)


def rollback(entries: list) -> None:
    failures = []
    for destination, workspace in reversed(entries):
        try:
            if os.path.lexists(workspace / "previous"):
                remove(destination)
                os.replace(workspace / "previous", destination)
            elif not os.path.lexists(workspace / "new"):
                remove(destination)
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
    prefix = prefix.absolute()
    prefix.mkdir(parents=True, exist_ok=True)
    # Lock the prefix directory without leaving a lock file in the installation.
    with prefix_lock(prefix):
        entries = []
        publishing = False
        preserve = False
        old_mask = None
        try:
            stage(source, prefix, entries)
            publishing = True
            publish(entries)
        except BaseException:
            # A second catchable signal must not interrupt recovery.
            old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
            if publishing:
                try:
                    rollback(entries)
                except BaseException:
                    preserve = True
                    raise
            raise
        finally:
            if old_mask is None:
                old_mask = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM, signal.SIGHUP})
            try:
                if not preserve:
                    for _, workspace in entries:
                        shutil.rmtree(workspace)
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
