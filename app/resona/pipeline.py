"""PipeWire plumbing: hosts the DSP plugin in a filter-chain and manages routing."""
from __future__ import annotations

import ctypes
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

SINK_NAME = os.environ.get("RESONA_SINK_NAME", "resona_sink")
OUT_NAME = SINK_NAME.replace("_sink", "") + "_output"
ROOT = Path(__file__).resolve().parents[2]


def find_plugin() -> str:
    cands = [
        os.environ.get("RESONA_PLUGIN", ""),
        str(ROOT / "engine" / "resona.so"),
        str(Path.home() / ".local/lib/resona/resona.so"),
        "/usr/lib/resona/resona.so",
        "/usr/lib/ladspa/resona.so",
    ]
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    raise FileNotFoundError("resona.so not found, run `make -C engine` first")


def _run(*args: str, timeout: float = 3.0) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


@dataclass
class Sink:
    name: str
    description: str
    kind: str  # headphones | speakers | hdmi | bluetooth | usb | other

    def as_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "kind": self.kind}


def _kind(s: dict) -> str:
    name = s.get("name", "")
    port = (s.get("active_port") or "").lower()
    props = s.get("properties", {})
    form = (props.get("device.form_factor") or "").lower()
    bus = (props.get("device.bus") or "").lower()
    if "bluez" in name or bus == "bluetooth":
        return "bluetooth"
    if "headphone" in port or form in ("headphone", "headset"):
        return "headphones"
    if "hdmi" in name or "hdmi" in port:
        return "hdmi"
    if bus == "usb" or "usb" in name:
        return "usb"
    if "speaker" in port or form in ("internal", "speaker"):
        return "speakers"
    return "speakers" if "analog" in name else "other"


def list_sinks() -> list[Sink]:
    out = _run("pactl", "-f", "json", "list", "sinks")
    try:
        data = json.loads(out or "[]")
    except json.JSONDecodeError:
        return []
    sinks = []
    for s in data:
        name = s.get("name", "")
        # skip our own sink and other effect sinks (routing into them would loop audio back)
        if name.startswith("resona") or "easyeffects" in name or "jamesdsp" in name.lower():
            continue
        sinks.append(Sink(name, s.get("description") or name, _kind(s)))
    return sinks


def sink_volume_db(name: str) -> float | None:
    """dB of the first channel of `name`, or None. Mute reads as -120 dB."""
    out = _run("pactl", "get-sink-volume", name)
    m = re.search(r"(-?inf|-?\d+(?:\.\d+)?) dB", out)
    if not m:
        return None
    if "mute: yes" in _run("pactl", "get-sink-mute", name):
        return -120.0
    return -120.0 if "inf" in m.group(1) else float(m.group(1))


def default_sink() -> str:
    return _run("pactl", "get-default-sink").strip()


def set_default_sink(name: str) -> None:
    _run("pactl", "set-default-sink", name)


def sink_exists(name: str) -> bool:
    return any(line.split("\t")[1] == name
               for line in _run("pactl", "list", "sinks", "short").splitlines()
               if "\t" in line)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def sink_channel_map(name: str) -> str:
    out = _run("pactl", "-f", "json", "list", "sinks")
    try:
        for s in json.loads(out or "[]"):
            if s.get("name") == name:
                return s.get("channel_map", "")
    except json.JSONDecodeError:
        pass
    return ""


def _ir_graph(ir: dict) -> tuple[list[str], list[str], list[str]]:
    """Convolver front-end: copy → convolver(s) → dry/wet mixer → resona inputs."""
    f, g, ch = _q(ir["path"]), ir.get("gain", 1.0), ir.get("channels", 2)
    mix = max(0.0, min(1.0, ir.get("mix", 1.0)))
    nodes = ['{ type = builtin label = copy name = cpL }', '{ type = builtin label = copy name = cpR }']
    links = []
    if ch == 4:  # true stereo: LL LR RL RR
        convs = [("cvLL", 0, "cpL", "mxL"), ("cvLR", 1, "cpL", "mxR"), ("cvRL", 2, "cpR", "mxL"), ("cvRR", 3, "cpR", "mxR")]
    else:
        convs = [("cvL", 0, "cpL", "mxL"), ("cvR", 1 if ch == 2 else 0, "cpR", "mxR")]
    port = {"mxL": 2, "mxR": 2}
    for name, c, src, dst in convs:
        nodes.append(f'{{ type = builtin label = convolver name = {name} config = {{ filename = {f} channel = {c} gain = {g:.6f} }} }}')
        links.append(f'{{ output = "{src}:Out" input = "{name}:In" }}')
        links.append(f'{{ output = "{name}:Out" input = "{dst}:In {port[dst]}" }}')
        port[dst] += 1
    for side in ("L", "R"):
        gains = " ".join(f'"Gain {i}" = {mix:.3f}' for i in range(2, port[f"mx{side}"]))
        nodes.append(f'{{ type = builtin label = mixer name = mx{side} control = {{ "Gain 1" = {1 - mix:.3f} {gains} }} }}')
        links.append(f'{{ output = "cp{side}:Out" input = "mx{side}:In 1" }}')
        links.append(f'{{ output = "mx{side}:Out" input = "resona:In {side}" }}')
    return nodes, links, ['"cpL:In"', '"cpR:In"']


def render_config(plugin: str, target: str | None, sink_name: str = SINK_NAME,
                  out_name: str = OUT_NAME, description: str = "Resona Sound",
                  layout: dict | None = None, ir: dict | None = None) -> str:
    """layout: hardware.layout_of(...) of the target; ir: correction.read_ir(...) + {"mix"}."""
    target_line = f"target.object = {_q(target)}" if target else ""
    surround = bool(layout and layout.get("channels", 2) > 2)
    if surround:
        positions = layout["positions"]
        label = "resona_surround"
        outputs = " ".join(f'"resona:Out {p}"' for p in positions)
    else:
        positions = ["FL", "FR"]
        label = "resona"
        outputs = '"resona:Out L" "resona:Out R"'
    nodes = [f"{{ type = ladspa name = resona plugin = {_q(plugin)} label = {label} }}"]
    links: list[str] = []
    inputs = '"resona:In L" "resona:In R"'
    if ir:
        n2, links, ins = _ir_graph(ir)
        nodes = n2 + nodes
        inputs = " ".join(ins)
    nl = "\n                    "
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
            node.description = {_q(description)}
            media.name       = {_q(description)}
            filter.graph = {{
                nodes = [
                    {nl.join(nodes)}
                ]
                links = [
                    {nl.join(links)}
                ]
                inputs  = [ {inputs} ]
                outputs = [ {outputs} ]
            }}
            capture.props = {{
                node.name   = {_q(sink_name)}
                media.class = Audio/Sink
                audio.channels = 2
                audio.position = [ FL FR ]
                device.icon-name = "audio-card"
            }}
            playback.props = {{
                node.name   = {_q(out_name)}
                node.passive = true
                node.dont-reconnect = true
                stream.dont-remix = true
                audio.channels = {len(positions)}
                audio.position = [ {" ".join(positions)} ]
                {target_line}
            }}
        }}
    }}
]
"""


def _pdeathsig():
    """Make the engine die with us, even on SIGKILL."""
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass


class Pipeline:
    def __init__(self, shm_path: str, sink_name: str = SINK_NAME, out_name: str = OUT_NAME,
                 description: str = "Resona Sound"):
        self.shm_path = shm_path
        self.description = description
        self.sink_name = sink_name
        self.out_name = out_name
        self.proc: subprocess.Popen | None = None
        self.target: str | None = None
        self.previous_default: str | None = None
        self.layout: dict | None = None
        self.ir: dict | None = None
        rt = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/resona-{os.getuid()}"
        self.conf = Path(rt) / "resona" / f"{sink_name}.conf"
        self.log = Path(rt) / "resona" / f"{sink_name}.log"

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def spawn(self, target: str | None, layout: dict | None = None, ir: dict | None = None) -> None:
        """Launch the engine process. Call from the main thread: PR_SET_PDEATHSIG
        is tied to the *thread* that forks, so a worker thread exiting would kill it."""
        self.stop(restore_default=False)
        self.target = target
        self.layout = layout
        self.ir = ir
        self.conf.parent.mkdir(parents=True, exist_ok=True)
        self.conf.write_text(render_config(find_plugin(), target, self.sink_name, self.out_name,
                                           self.description, layout, ir))
        env = dict(os.environ, RESONA_SHM=self.shm_path)
        with open(self.log, "w") as log:
            self.proc = subprocess.Popen(["pipewire", "-c", str(self.conf)], env=env, stdout=log,
                                         stderr=subprocess.STDOUT, preexec_fn=_pdeathsig)

    def wait_ready(self, make_default: bool = True, timeout: float = 4.0) -> bool:
        """Block until the virtual sink exists; safe to call from any thread."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.running:
                return False
            if sink_exists(self.sink_name):
                break
            time.sleep(0.1)
        else:
            return False
        if make_default:
            cur = default_sink()
            if cur and cur != self.sink_name:
                self.previous_default = cur
            set_default_sink(self.sink_name)
        return True

    def start(self, target: str | None, make_default: bool = True, timeout: float = 4.0) -> bool:
        self.spawn(target)
        return self.wait_ready(make_default, timeout)

    def stop(self, restore_default: bool = True) -> None:
        if restore_default and default_sink() == self.sink_name:
            fallback = self.target or self.previous_default  # the device actually in use
            if fallback:
                set_default_sink(fallback)
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
