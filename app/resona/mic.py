"""Resona Microphone: a "Resona Microphone" virtual source that cleans up (and, for fun,
transforms) the voice from a real microphone. Hosts the "resona_mic" LADSPA label in its
own PipeWire filter-chain, separate from the playback engine.
"""
from __future__ import annotations

import ctypes
import json
import mmap
import os
import signal
import struct
import subprocess
import threading
import time
from pathlib import Path

from . import pipeline
from .shm import _store_u32

MIC_NAME = os.environ.get("RESONA_MIC_NAME", "resona_mic")
CAPTURE_NAME = MIC_NAME + "_capture"

# --- shared memory, mirror of engine/resona_mic_shm.h --------------------------------
MAGIC = 0x434D5352
VERSION = 1
NPARAMS = 16
OFF_MAGIC, OFF_VERSION, OFF_SEQ, OFF_CONTROL_SEQ = 0, 4, 8, 12
OFF_PARAMS = 16
OFF_RATE = OFF_PARAMS + NPARAMS * 4          # 80
OFF_HEARTBEAT = OFF_RATE + 4                 # 84
OFF_METERS = OFF_HEARTBEAT + 4               # 88: in_peak, out_peak, nr_db, agc_db
SIZE = OFF_METERS + 4 * 4 + 10 * 4           # 144

PARAMS = ["enable", "gain", "hpf", "ns", "clarity", "agc", "agc_target", "voice", "pitch"]
INDEX = {n: i for i, n in enumerate(PARAMS)}
DEFAULTS = {"enable": 1, "gain": 0, "hpf": 1, "ns": 0.5, "clarity": 0.4, "agc": 1,
            "agc_target": -18, "voice": 0, "pitch": 0}
RANGES = {"enable": (0, 1), "gain": (-12, 24), "hpf": (0, 1), "ns": (0, 1), "clarity": (0, 1),
          "agc": (0, 1), "agc_target": (-30, -10), "voice": (0, 6), "pitch": (-12, 12)}

# voice changer modes (engine order) and the pitch each one starts at
VOICES = ["Off", "Deep", "Chipmunk", "Robot", "Radio", "Alien", "Cave"]
VOICE_PITCH = {"Deep": -5, "Chipmunk": 7, "Alien": 4}


def default_shm_path() -> str:
    return os.environ.get("RESONA_MIC_SHM") or f"/dev/shm/resona-mic-{os.getuid()}"


def clamp_params(values: dict) -> dict:
    out = {}
    for k, v in values.items():
        if k in RANGES:
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            if v != v:          # NaN
                continue
            lo, hi = RANGES[k]
            out[k] = min(hi, max(lo, v))
    return out


class MicState:
    """UI side of the mic shared memory; writes use the same odd/even publication guard."""

    def __init__(self, path: str | None = None):
        self.path = path or default_shm_path()
        self.closed = False
        self._lock = threading.RLock()
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.fstat(fd).st_size < SIZE:
                os.ftruncate(fd, SIZE)
            self.mm = mmap.mmap(fd, SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        finally:
            os.close(fd)
        self._address = ctypes.addressof(ctypes.c_char.from_buffer(self.mm))
        if self._u32(OFF_MAGIC) != MAGIC or self._u32(OFF_VERSION) != VERSION:
            for i in range(NPARAMS):
                struct.pack_into("<f", self.mm, OFF_PARAMS + 4 * i, 0.0)
            struct.pack_into("<I", self.mm, OFF_CONTROL_SEQ, 0)
            struct.pack_into("<I", self.mm, OFF_VERSION, VERSION)
            struct.pack_into("<I", self.mm, OFF_MAGIC, MAGIC)
            self.write(DEFAULTS)

    def _u32(self, off: int) -> int:
        with self._lock:
            if self.closed:
                return 0
            return struct.unpack_from("<I", self.mm, off)[0]

    def write(self, values: dict) -> None:
        words = []
        for k, v in clamp_params(values).items():
            bits = struct.unpack("<I", struct.pack("<f", v))[0]
            words.append((OFF_PARAMS + INDEX[k] * 4, bits))
        with self._lock:
            if self.closed or not words:
                return
            seq = ((self._u32(OFF_CONTROL_SEQ) + 1) | 1) & 0xFFFFFFFF
            _store_u32(self._address + OFF_CONTROL_SEQ, seq, 5)
            for offset, value in words:
                _store_u32(self._address + offset, value, 0)
            _store_u32(self._address + OFF_SEQ, (self._u32(OFF_SEQ) + 1) & 0xFFFFFFFF, 0)
            _store_u32(self._address + OFF_CONTROL_SEQ, (seq + 1) & 0xFFFFFFFF, 5)

    def params(self) -> dict:
        with self._lock:
            if self.closed:
                return {}
            return {k: struct.unpack_from("<f", self.mm, OFF_PARAMS + 4 * i)[0] for i, k in enumerate(PARAMS)}

    @property
    def heartbeat(self) -> int:
        return self._u32(OFF_HEARTBEAT)

    def meters(self) -> dict:
        with self._lock:
            if self.closed:
                return dict(in_peak=0.0, out_peak=0.0, nr_db=0.0, agc_db=0.0)
            a, b, c, d = struct.unpack_from("<4f", self.mm, OFF_METERS)
        return dict(in_peak=a, out_peak=b, nr_db=c, agc_db=d)

    def close(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
            try:
                self.mm.close()
            except (BufferError, ValueError):
                pass


# --- devices -------------------------------------------------------------------------
def _json(*args: str) -> list:
    try:
        data = json.loads(pipeline._run(*args) or "[]")
    except json.JSONDecodeError:
        return []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _source_kind(src: dict) -> str:
    props = src.get("properties", {}) if isinstance(src.get("properties"), dict) else {}
    bus = (props.get("device.bus") or "").lower()
    form = (props.get("device.form_factor") or "").lower()
    if "bluez" in src.get("name", "") or bus == "bluetooth":
        return "bluetooth"
    if form in ("webcam",):
        return "webcam"
    if bus == "usb":
        return "usb"
    if form in ("headset", "headphone"):
        return "headset"
    return "builtin"


def list_sources() -> list[dict]:
    """Real capture devices (no monitors, no Resona or other virtual mics)."""
    out = []
    for s in _json("pactl", "-f", "json", "list", "sources"):
        name = s.get("name", "")
        props = s.get("properties", {}) if isinstance(s.get("properties"), dict) else {}
        if (not name or name.endswith(".monitor") or s.get("monitor_of_sink") not in (None, "", "n/a")
                or name.startswith(MIC_NAME) or props.get("media.class") not in (None, "Audio/Source", "Audio/Source/Virtual")
                or props.get("device.class") == "monitor"):
            continue
        out.append({"name": name, "description": s.get("description") or name, "kind": _source_kind(s),
                    "muted": bool(s.get("mute"))})
    return out


def default_source() -> str:
    return pipeline._run("pactl", "get-default-source").strip()


def set_default_source(name: str) -> bool:
    try:
        return subprocess.run(["pactl", "set-default-source", name], capture_output=True, timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def source_exists(name: str) -> bool:
    return any(line.split("\t")[1:2] == [name] for line in pipeline._run("pactl", "list", "short", "sources").splitlines())


# --- engine process ---------------------------------------------------------------------
def render_mic_config(plugin: str, source: str | None, mic_name: str = MIC_NAME,
                      capture_name: str = CAPTURE_NAME, description: str = "Resona Microphone") -> str:
    q = pipeline._q
    target_line = f"target.object = {q(source)}" if source else ""
    return f"""# generated by Resona, do not edit
context.properties = {{ log.level = 0 }}
context.spa-libs = {{
    audio.convert.* = audioconvert/libspa-audioconvert
    support.*       = support/libspa-support
}}
context.modules = [
    {{ name = libpipewire-module-rt args = {{ nice.level = -11 }} flags = [ ifexists nofail ] }}
    {{ name = libpipewire-module-protocol-native }}
    {{ name = libpipewire-module-client-node }}
    {{ name = libpipewire-module-adapter }}
    {{ name = libpipewire-module-filter-chain
        args = {{
            node.description = {q(description)}
            media.name       = {q(description)}
            filter.graph = {{
                nodes = [
                    {{ type = ladspa name = mic plugin = {q(plugin)} label = resona_mic }}
                ]
                inputs  = [ "mic:In" ]
                outputs = [ "mic:Out" ]
            }}
            capture.props = {{
                node.name      = {q(capture_name)}
                node.passive   = true
                node.dont-reconnect = true
                audio.channels = 1
                audio.position = [ MONO ]
                {target_line}
            }}
            playback.props = {{
                node.name      = {q(mic_name)}
                media.class    = Audio/Source
                audio.channels = 1
                audio.position = [ MONO ]
                device.icon-name = "audio-input-microphone"
            }}
        }}
    }}
]
"""


class MicPipeline:
    def __init__(self, shm_path: str, mic_name: str = MIC_NAME, capture_name: str = CAPTURE_NAME,
                 description: str = "Resona Microphone"):
        self.shm_path = shm_path
        self.mic_name = mic_name
        self.capture_name = capture_name
        self.description = description
        self.proc: subprocess.Popen | None = None
        self.source: str | None = None
        self.previous_default: str | None = None
        self.claimed_default = False      # only hand back a default we actually took
        self._lock = threading.Lock()
        rt = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/resona-{os.getuid()}"
        self.conf = Path(rt) / "resona" / f"{mic_name}.conf"
        self.log = Path(rt) / "resona" / f"{mic_name}.log"

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def spawn(self, source: str | None) -> None:
        """Main thread only (PR_SET_PDEATHSIG belongs to the forking thread)."""
        self.stop(restore_default=False)
        self.source = source
        self.conf.parent.mkdir(parents=True, exist_ok=True)
        self.conf.write_text(render_mic_config(pipeline.find_plugin(), source, self.mic_name,
                                               self.capture_name, self.description))
        env = dict(os.environ, RESONA_MIC_SHM=self.shm_path)
        with open(self.log, "w") as log:
            self.proc = subprocess.Popen(["pipewire", "-c", str(self.conf)], env=env, stdout=log,
                                         stderr=subprocess.STDOUT, preexec_fn=pipeline._pdeathsig)

    def wait_ready(self, make_default: bool, timeout: float = 4.0) -> bool:
        proc = self.proc
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc is None or self.proc is not proc or proc.poll() is not None:
                return False
            if source_exists(self.mic_name):
                break
            time.sleep(0.1)
        else:
            return False
        with self._lock:
            if self.proc is not proc or proc.poll() is not None:
                return False
            if make_default and not self._claim_locked():
                return False
            return True

    def _claim_locked(self) -> bool:
        cur = default_source()
        if cur != self.mic_name:
            if not set_default_source(self.mic_name):
                return False
            if cur:
                self.previous_default = cur
        self.claimed_default = True
        return True

    def claim_default(self) -> bool:
        """Make Resona Microphone the system default input."""
        with self._lock:
            return self.running and self._claim_locked()

    def release_default(self) -> None:
        """Hand the default input back to the real microphone, if we took it and still hold it."""
        with self._lock:
            if not self.claimed_default:
                return
            self.claimed_default = False
            if default_source() == self.mic_name:
                fallback = self.source or self.previous_default
                if fallback:
                    set_default_source(fallback)

    def stop(self, restore_default: bool = True) -> None:
        if restore_default:
            self.release_default()
        with self._lock:
            if self.proc is not None:
                if self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(2)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait()
                self.proc = None

    def last_log(self) -> str:
        try:
            return self.log.read_text()[-2000:]
        except OSError:
            return ""


# --- "hear yourself" test ---------------------------------------------------------------
def record_test(seconds: float, path: Path, source: str = MIC_NAME) -> bool:
    """Record a few seconds from the processed mic into a WAV file (PipeWire-native recorder)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.Popen(["pw-record", "--target", source, "--rate", "48000", "--channels", "1",
                                 "--format", "s16", str(path)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return False
    time.sleep(seconds)
    proc.send_signal(signal.SIGINT)          # lets it finish the WAV header
    try:
        proc.wait(3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    return path.is_file() and path.stat().st_size > 1000


def play_file(path: Path) -> bool:
    try:
        return subprocess.run(["pw-play", str(path)], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
