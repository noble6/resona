"""State and preset file I/O, independent of Qt and the audio controller."""
import json
import os
from pathlib import Path
import re
import tempfile

from . import validation

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "resona"
STATE_FILE = CONFIG_DIR / "state.json"
PRESET_DIR = CONFIG_DIR / "presets"


def read_json(path: Path):
    return json.loads(path.read_bytes())


def load_state() -> dict:
    try:
        return validation.state(read_json(STATE_FILE))
    except (OSError, ValueError):
        return {}


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        # A unique sibling avoids collisions and keeps replacement on one filesystem.
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, data) -> None:
    # Serialize first so invalid data cannot touch an existing file.
    atomic_write(path, json.dumps(data, indent=1, allow_nan=False).encode("utf-8"))


def save_state(data: dict) -> None:
    write_json(STATE_FILE, data)


def preset_path(name: str) -> Path:
    return PRESET_DIR / (re.sub(r"[^\w\- ]", "_", name).strip() + ".json")


def user_presets() -> list[str]:
    try:
        return sorted(path.stem for path in PRESET_DIR.glob("*.json"))
    except OSError:
        return []


def delete_preset(name: str) -> None:
    try:
        preset_path(name).unlink()
    except OSError:
        pass


def import_preset(source: Path, destination: Path) -> dict:
    content = source.read_bytes()
    data = json.loads(content)
    if not isinstance(data, dict) or "params" not in data:
        raise ValueError("not a Resona preset")
    data = validation.snapshot(data)
    atomic_write(destination, content)
    return data


def copy_file(source: Path, destination: Path) -> None:
    atomic_write(destination, source.read_bytes())
