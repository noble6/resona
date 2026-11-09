"""Headphone/speaker correction: AutoEq database, EqualizerAPO / AutoEq parametric files,
ViPER DDC (.vdc) biquad files and impulse responses (.wav / .irs) for the convolver."""
from __future__ import annotations

import os
import re
import struct
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

AUTOEQ_RAW = "https://raw.githubusercontent.com/jaakkopasanen/AutoEq/master/results"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "resona"
UA = {"User-Agent": "Resona-sound-engine"}
MAX_IR_BYTES = 64 * 1024 * 1024


# ---------------------------------------------------------------- AutoEq
def _get(url: str, timeout: float = 20) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def autoeq_index(max_age_days: float = 7) -> list[dict]:
    """[{name, path, source}] for ~9k headphones. Cached on disk."""
    cache = CACHE_DIR / "autoeq_index.md"
    text = None
    if cache.exists() and time.time() - cache.stat().st_mtime < max_age_days * 86400:
        text = cache.read_text()
    if text is None:
        try:
            text = _get(f"{AUTOEQ_RAW}/INDEX.md")
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache.write_text(text)
        except OSError:
            text = cache.read_text() if cache.exists() else ""
    out = []
    for m in re.finditer(r"^- \[(.+?)\]\(\./(.+?)\) by (.+?)(?: on (.+))?$", text, re.M):
        out.append({"name": m.group(1), "path": m.group(2), "source": m.group(3) + (f" · {m.group(4)}" if m.group(4) else "")})
    return out


def autoeq_search(index: list[dict], query: str, limit: int = 40) -> list[dict]:
    q = [w for w in query.lower().split() if w]
    if not q:
        return []
    scored = []
    for e in index:
        n = e["name"].lower()
        if all(w in n for w in q):
            scored.append((0 if n.startswith(q[0]) else 1, len(n), e))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [e for *_, e in scored[:limit]]


def autoeq_fetch(entry: dict) -> str:
    name = entry["name"]
    url = f"{AUTOEQ_RAW}/{entry['path']}/{urllib.parse.quote(name)}%20ParametricEQ.txt"
    return _get(url)


# ---------------------------------------------------------------- EqualizerAPO / AutoEq text
_TYPE_ALIASES = {"PK": "PK", "PEQ": "PK", "LS": "LSC", "LSC": "LSC", "LSQ": "LSC", "HS": "HSC", "HSC": "HSC",
                 "HSQ": "HSC", "LP": "LP", "LPQ": "LP", "HP": "HP", "HPQ": "HP"}


def parse_parametric(text: str) -> tuple[float, list[dict]]:
    """Parse EqualizerAPO-style 'Preamp:' and 'Filter n: ON PK Fc X Hz Gain Y dB Q Z' lines."""
    preamp = 0.0
    filters = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"(?i)preamp:\s*(-?[\d.]+)\s*db", line)
        if m:
            preamp += float(m.group(1))
            continue
        m = re.match(r"(?i)filter\s*\d*:\s*(ON|OFF)\s+([A-Z]+)(?:\s+\d+\s*dB)?\s+(.*)$", line)
        if not m or m.group(1).upper() != "ON":
            continue
        ftype = _TYPE_ALIASES.get(m.group(2).upper())
        if not ftype:
            continue
        rest = m.group(3)
        fc = re.search(r"(?i)fc\s+(-?[\d.]+)\s*(k?)hz", rest)
        gain = re.search(r"(?i)gain\s+(-?[\d.]+)\s*db", rest)
        q = re.search(r"(?i)\bq\s+([\d.]+)", rest)
        if not fc:
            continue
        f = float(fc.group(1)) * (1000 if fc.group(2) else 1)
        filters.append({"type": ftype, "freq": f, "gain": float(gain.group(1)) if gain else 0.0,
                        "q": float(q.group(1)) if q else 0.7071})
    return preamp, filters[:24]


# ---------------------------------------------------------------- ViPER DDC
def parse_vdc(text: str, fs: int) -> list[dict]:
    """Biquads from a ViPER-DDC file for the exact playback rate.
    File order per section: b0 b1 b2 a1 a2 with a1/a2 stored negated (JamesDSP vdc.c)."""
    sections = {}
    for m in re.finditer(r"SR_(\d+)\s*:\s*([-\d.,eE+\s]+)", text):
        vals = [float(v) for v in m.group(2).replace("\n", "").split(",") if v.strip()]
        sections[int(m.group(1))] = vals
    if not sections:
        raise ValueError("no SR_44100 / SR_48000 section found")
    if fs not in sections:
        raise ValueError(f"DDC has no {fs} Hz section")
    v = sections[fs]
    if not v or len(v) % 5:
        raise ValueError("incomplete DDC biquad section")
    out = []
    for i in range(0, len(v) - 4, 5):
        b0, b1, b2, a1, a2 = v[i:i + 5]
        out.append({"type": "RAW", "b0": b0, "b1": b1, "b2": b2, "a1": -a1, "a2": -a2})
    return out[:24]


# ---------------------------------------------------------------- response math (matches the engine)
def _rbj(t: str, f: float, g: float, q: float, fs: float):
    A = 10 ** (g / 40)
    w = 2 * np.pi * min(f, fs * 0.45) / fs
    cw, sw = np.cos(w), np.sin(w)
    al = sw / (2 * max(q, 0.05))
    sA = 2 * np.sqrt(A) * al
    if t == "PK":
        b, a = [1 + al * A, -2 * cw, 1 - al * A], [1 + al / A, -2 * cw, 1 - al / A]
    elif t == "LSC":
        b = [A * ((A + 1) - (A - 1) * cw + sA), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sA)]
        a = [(A + 1) + (A - 1) * cw + sA, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sA]
    elif t == "HSC":
        b = [A * ((A + 1) + (A - 1) * cw + sA), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - sA)]
        a = [(A + 1) - (A - 1) * cw + sA, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - sA]
    elif t == "LP":
        b, a = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2], [1 + al, -2 * cw, 1 - al]
    elif t == "HP":
        b, a = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2], [1 + al, -2 * cw, 1 - al]
    else:
        return [1, 0, 0], [1, 0, 0]
    return [x / a[0] for x in b], [1, a[1] / a[0], a[2] / a[0]]


def response_db(filters: list[dict], freqs: np.ndarray, fs: float = 48000.0, preamp: float = 0.0) -> np.ndarray:
    z = np.exp(-1j * 2 * np.pi * freqs / fs)
    h = np.ones_like(z) * 10 ** (preamp / 20)
    for f in filters:
        if f.get("type") == "RAW":
            b, a = [f["b0"], f["b1"], f["b2"]], [1, f["a1"], f["a2"]]
        else:
            b, a = _rbj(f["type"], f["freq"], f.get("gain", 0), f.get("q", 0.7071), fs)
        h = h * (b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)
    return 20 * np.log10(np.abs(h) + 1e-12)


def safe_preamp(filters: list[dict], fs: float = 48000.0) -> float:
    """Preamp (dB, <= 0) that keeps the correction's peak at 0 dB."""
    peak = float(response_db(filters, np.geomspace(20, 20000, 400), fs).max())
    return round(-max(0.0, peak), 1)


# ---------------------------------------------------------------- impulse responses
def read_ir(path: str) -> dict:
    """Inspect a WAV/IRS impulse response: channels, rate, length and a safe gain."""
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_IR_BYTES + 1)
    if len(data) > MAX_IR_BYTES:
        raise ValueError("impulse response exceeds 64 MiB")
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    pos, fmt, raw = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        if pos + 8 + size > len(data):
            raise ValueError("truncated WAV chunk")
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            if len(body) < 16:
                raise ValueError("truncated WAV format")
            tag, ch, rate, _, _, bits = struct.unpack_from("<HHIIHH", body)
            if tag == 0xFFFE:
                if len(body) < 40:
                    raise ValueError("truncated extensible WAV format")
                tag = struct.unpack_from("<H", body, 24)[0]
            fmt = (tag, ch, rate, bits)
        elif cid == b"data":
            raw = body
        pos += 8 + size + (size & 1)
    if not fmt or raw is None:
        raise ValueError("missing fmt/data chunk")
    tag, ch, rate, bits = fmt
    if rate <= 0:
        raise ValueError("invalid WAV sample rate")
    if ch not in (1, 2, 4):
        raise ValueError(f"{ch}-channel IR: need mono, stereo or true-stereo (4 ch)")
    if bits <= 0 or bits % 8 or len(raw) % (ch * (bits // 8)):
        raise ValueError("incomplete WAV sample frame")
    if tag == 3 and bits == 32:
        x = np.frombuffer(raw[: len(raw) // 4 * 4], "<f4")
    elif tag == 3 and bits == 64:
        x = np.frombuffer(raw[: len(raw) // 8 * 8], "<f8")
    elif tag == 1 and bits == 16:
        x = np.frombuffer(raw[: len(raw) // 2 * 2], "<i2") / 32768.0
    elif tag == 1 and bits == 24:
        b = np.frombuffer(raw[: len(raw) // 3 * 3], np.uint8).reshape(-1, 3)
        x = ((b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16)) << 8 >> 8) / 8388608.0
    elif tag == 1 and bits == 32:
        x = np.frombuffer(raw[: len(raw) // 4 * 4], "<i4") / 2147483648.0
    else:
        raise ValueError(f"unsupported WAV format (tag {tag}, {bits} bit)")
    x = np.asarray(x, dtype=np.float64)[: len(x) // ch * ch].reshape(-1, ch)
    if len(x) < 2:
        raise ValueError("empty impulse response")
    if not np.isfinite(x).all():
        raise ValueError("non-finite impulse response samples")
    # gain so the loudest frequency of the (summed) response sits at 0 dB
    n = 1 << int(np.ceil(np.log2(len(x) * 2)))
    if ch == 4:
        paths = [x[:, 0] + x[:, 2], x[:, 1] + x[:, 3]]
    else:
        paths = [x[:, c] for c in range(ch)]
    peak = max(float(np.abs(np.fft.rfft(p, n)).max()) for p in paths)
    return {"path": str(path), "channels": ch, "rate": rate, "frames": len(x),
            "seconds": round(len(x) / rate, 3), "gain": round(1.0 / peak, 6) if peak > 0 else 1.0}
