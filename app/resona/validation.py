"""Validate persisted audio settings before they reach the controller or DSP."""
import math

from . import presets

PARAM_LIMITS = {name: (0, 1) for name in presets.DEFAULTS}
PARAM_LIMITS.update({f"eq{i}": (-15, 15) for i in range(10)})
PARAM_LIMITS.update({
    "preamp": (-24, 12), "output": (-24, 12), "bass_freq": (40, 250),
    "stage_width": (0, 2), "lev_target": (-30, -6), "lim_ceil": (-12, 0),
    "sysvol_db": (-120, 0), "ieq_target": (0, 3), "hrtf_angle": (10, 70),
    "corr_preamp": (-120, 12), "layout": (0, 15), "bass_type": (0, 3),
})


def number(value, low, high):
    if not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value):
        raise ValueError(f"expected a finite number between {low} and {high}")
    return value


def params(data):
    if not isinstance(data, dict):
        raise ValueError("params must be an object")
    return {key: number(value, *PARAM_LIMITS[key]) for key, value in data.items() if key in PARAM_LIMITS}


def correction(data):
    if data is None or data == {}:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("filters", []), list):
        raise ValueError("correction must contain a filter list")
    for key in ("name", "source", "kind", "text"):
        if key in data and not isinstance(data[key], str):
            raise ValueError(f"correction {key} must be text")
    number(data.get("preamp", 0), -120, 12)
    # Older versions stored every imported section although DSP used only 24.
    filters = data.get("filters", [])[:24]
    for section in filters:
        if not isinstance(section, dict):
            raise ValueError("correction filter must be an object")
        kind = section.get("type")
        if kind == "RAW":
            for key in ("b0", "b1", "b2", "a1", "a2"):
                number(section.get(key), -1e6, 1e6)
            if abs(section["a2"]) >= 1 or abs(section["a1"]) >= 1 + section["a2"]:
                raise ValueError("unstable correction filter")
        elif kind in ("PK", "LSC", "HSC", "LP", "HP"):
            number(section.get("freq"), 0.01, 384000)
            number(section.get("gain", 0), -24, 24)
            number(section.get("q", 0.7071), 0.01, 1000)
        else:
            raise ValueError("unknown correction filter type")
    return dict(data, filters=filters)


def snapshot(data):
    if not isinstance(data, dict):
        raise ValueError("settings must be an object")
    result = dict(data)
    result["params"] = params(data.get("params", {}))
    for key, choices in (("profile", presets.PROFILES), ("device", presets.DEVICE_MODES),
                         ("eq_preset", presets.EQ_PRESETS)):
        if key in data and (not isinstance(data[key], str) or data[key] not in choices):
            raise ValueError(f"unknown {key}")
    if "modified" in data and not isinstance(data["modified"], bool):
        raise ValueError("modified must be a boolean")
    if "correction" in data:
        result["correction"] = correction(data["correction"])
    return result


def state(data):
    result = snapshot(data)
    for key in ("app_auto", "capture_all", "per_device", "follow", "dark", "update_auto", "reduced_motion"):
        if key in data and not isinstance(data[key], bool):
            raise ValueError(f"{key} must be a boolean")
    for key in ("output", "last_target", "accent"):
        if data.get(key) is not None and not isinstance(data[key], str):
            raise ValueError(f"{key} must be text")
    for key in ("app_rules", "device_memory"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError(f"{key} must be an object")
    for profile in data.get("app_rules", {}).values():
        if not isinstance(profile, str) or profile not in presets.PROFILES:
            raise ValueError("unknown app profile")
    result["device_memory"] = {name: snapshot(value) for name, value in data.get("device_memory", {}).items()}
    if "update_last" in data:
        number(data["update_last"], 0, 1e12)
    if "update_freq" in data and data["update_freq"] not in ("manual", "weekly", "monthly"):
        raise ValueError("unknown update schedule")
    ir = data.get("ir")
    if ir is not None:
        if not isinstance(ir, dict) or not isinstance(ir.get("path"), str):
            raise ValueError("impulse response must contain a path")
        if not isinstance(ir.get("on", False), bool):
            raise ValueError("impulse response on must be a boolean")
        number(ir.get("mix", 1), 0, 1)
        number(ir.get("gain", 1), 0, 1e6)
        if ir.get("channels", 2) not in (1, 2, 4):
            raise ValueError("invalid impulse response channels")
    return result
