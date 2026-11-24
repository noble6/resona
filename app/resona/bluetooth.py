"""Bluetooth audio auto-connect through BlueZ on the system D-Bus.

Uses `busctl --auto-start=no`, so asking about Bluetooth never starts a bluetoothd the
user switched off. Every call is bounded by a timeout; nothing here blocks the UI thread
when run through Backend._async.
"""
from __future__ import annotations

import json
import subprocess

A2DP_SINK = "0000110b-0000-1000-8000-00805f9b34fb"
AUDIO_UUIDS = {
    A2DP_SINK,
    "0000111e-0000-1000-8000-00805f9b34fb",   # Hands-Free
    "00001108-0000-1000-8000-00805f9b34fb",   # Headset
    "00001203-0000-1000-8000-00805f9b34fb",   # Generic Audio
    "0000184e-0000-1000-8000-00805f9b34fb",   # LE Audio stream control
}
SERVICE_OFF = "Bluetooth service is not running"


def _busctl(*args: str, timeout: float = 6.0) -> tuple[bool, str]:
    cmd = ["busctl", "--system", "--auto-start=no", "--json=short", *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return r.returncode == 0, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout).strip())


def _val(props: dict, key: str, default=None):
    v = props.get(key)
    return v.get("data", default) if isinstance(v, dict) else default


def parse_objects(data: dict) -> dict:
    """GetManagedObjects (busctl JSON) -> {"adapter": {...}|None, "devices": [...]}."""
    objects = {}
    payload = data.get("data") if isinstance(data, dict) else None
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        objects = payload[0]
    adapter, devices = None, []
    for path, ifaces in sorted(objects.items()):
        if not isinstance(ifaces, dict):
            continue
        a = ifaces.get("org.bluez.Adapter1")
        if isinstance(a, dict) and adapter is None:
            adapter = {"path": path, "powered": bool(_val(a, "Powered", False)),
                       "name": _val(a, "Alias") or _val(a, "Name") or path.rsplit("/", 1)[-1]}
        d = ifaces.get("org.bluez.Device1")
        if isinstance(d, dict):
            uuids = {u.lower() for u in (_val(d, "UUIDs", []) or []) if isinstance(u, str)}
            icon = _val(d, "Icon", "") or ""
            audio = bool(uuids & AUDIO_UUIDS) or icon.startswith("audio-")
            devices.append({
                "path": path, "address": _val(d, "Address", ""), "name": _val(d, "Alias") or _val(d, "Name") or "",
                "icon": icon, "paired": bool(_val(d, "Paired", False)), "trusted": bool(_val(d, "Trusted", False)),
                "connected": bool(_val(d, "Connected", False)), "audio": audio,
            })
    return {"adapter": adapter, "devices": devices}


def status() -> dict:
    """{"service": bool, "error": str, "adapter": {...}|None, "devices": [paired audio devices]}"""
    ok, out = _busctl("call", "org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")
    if not ok:
        off = any(t in out for t in ("org.bluez", "NameHasNoOwner", "not activatable", "not provided",
                                       "does not exist", "ServiceUnknown"))
        return {"service": False, "error": SERVICE_OFF if off or not out else out, "adapter": None, "devices": []}
    try:
        parsed = parse_objects(json.loads(out))
    except (json.JSONDecodeError, AttributeError, TypeError):
        return {"service": True, "error": "Unexpected reply from Bluetooth", "adapter": None, "devices": []}
    devices = [d for d in parsed["devices"] if d["paired"] and d["audio"] and d["address"]]
    return {"service": True, "error": "" if parsed["adapter"] else "No Bluetooth adapter",
            "adapter": parsed["adapter"], "devices": devices}


def connect(path: str) -> tuple[bool, str]:
    if not path.startswith("/org/bluez/"):
        return False, "invalid device"
    ok, out = _busctl("--timeout=20", "call", "org.bluez", path, "org.bluez.Device1", "Connect", timeout=25)
    return ok, "" if ok else (out.splitlines()[-1] if out else "connection failed")


def disconnect(path: str) -> tuple[bool, str]:
    if not path.startswith("/org/bluez/"):
        return False, "invalid device"
    ok, out = _busctl("--timeout=10", "call", "org.bluez", path, "org.bluez.Device1", "Disconnect", timeout=15)
    return ok, "" if ok else (out.splitlines()[-1] if out else "disconnect failed")


class AutoConnect:
    """Decides which paired audio devices to dial, with backoff so absent devices cost little.

    A device that the user (or the device) just disconnected is left alone for a while,
    so turning headphones off or disconnecting them by hand is not undone seconds later.
    """
    FIRST_RETRY = 15.0
    MAX_RETRY = 300.0
    AFTER_DISCONNECT = 120.0

    def __init__(self):
        self.next_try: dict[str, float] = {}
        self.backoff: dict[str, float] = {}
        self.was_connected: dict[str, bool] = {}

    def due(self, devices: list[dict], enabled: dict, now: float) -> list[dict]:
        out = []
        for d in devices:
            addr = d["address"]
            if self.was_connected.get(addr) and not d["connected"]:
                # it dropped since the last look: give the user a quiet period
                self.next_try[addr] = now + self.AFTER_DISCONNECT
                self.backoff[addr] = self.FIRST_RETRY
            self.was_connected[addr] = d["connected"]
            if d["connected"]:
                self.backoff.pop(addr, None)
                self.next_try.pop(addr, None)
                continue
            if not enabled.get(addr, True):
                continue
            if now >= self.next_try.get(addr, 0.0):
                out.append(d)
        return out

    def result(self, address: str, ok: bool, now: float) -> None:
        if ok:
            self.backoff.pop(address, None)
            self.next_try.pop(address, None)
            self.was_connected[address] = True
            return
        delay = min(self.MAX_RETRY, self.backoff.get(address, self.FIRST_RETRY / 2) * 2)
        self.backoff[address] = delay
        self.next_try[address] = now + delay

    def reset(self) -> None:
        """Adapter powered on, or the system resumed: try everyone again now."""
        self.next_try.clear()
        self.backoff.clear()
