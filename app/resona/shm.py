"""Shared-memory bridge to the DSP engine (mirror of engine/resona_shm.h, v3).

Offsets are asserted against the C layout printed by `make -C engine test`.
"""
from __future__ import annotations

import mmap
import ctypes
import os
import struct
import threading

import numpy as np

MAGIC = 0x414E5352
VERSION = 3
NPARAMS = 128
RING = 4096
NCORR = 24
NBANDS = 10

OFF_MAGIC, OFF_VERSION, OFF_SEQ, OFF_RATE = 0, 4, 8, 12
OFF_PARAMS = 16
OFF_HEARTBEAT = 528
OFF_RING_POS = 532
OFF_IN_PEAK = 536
OFF_OUT_PEAK = 544
OFF_LEVELER = 552           # leveler, limiter, loudness, content (4 floats)
OFF_IEQ = 568
OFF_OUT_CH = 608
OFF_CORR_COUNT = 612
OFF_CONTROL_SEQ = 616
OFF_CORR = 640              # NCORR x 10 floats
OFF_RING_IN = 1600
OFF_RING_OUT = OFF_RING_IN + RING * 4
SIZE = OFF_RING_OUT + RING * 4  # 34368

PARAMS = [
    "enable", "preamp", "output",
    "eq_on", *[f"eq{i}" for i in range(10)],
    "bass_on", "bass_amt", "bass_freq", "bass_punch",
    "clar_on", "clar_amt",
    "voice_on", "voice_amt",
    "stage_on", "stage_width", "stage_depth",
    "xfeed_on", "xfeed_amt",
    "amb_on", "amb_mix", "amb_size", "amb_damp",
    "lev_on", "lev_amt", "lev_target",
    "loud_on", "loud_amt",
    "lim_on", "lim_ceil",
    "sysvol_db",
    # v2
    "ieq_on", "ieq_amt", "ieq_target",
    "tube_on", "tube_drive",
    "hrtf_on", "hrtf_angle", "hrtf_amt",
    "corr_on", "corr_preamp",
    "upmix_on", "upmix_center", "upmix_surr", "upmix_lfe",
    "layout",
    # v2.1
    "bass_type",
]
INDEX = {n: i for i, n in enumerate(PARAMS)}

# correction filter types (engine CORR_*)
CORR_TYPES = {"OFF": 0, "PK": 1, "LSC": 2, "HSC": 3, "LP": 4, "HP": 5, "RAW": 6}

# Match the engine's 32-bit atomic accesses, including on weakly ordered CPUs.
_atomic = ctypes.CDLL("libatomic.so.1")
_store_u32 = _atomic.__atomic_store_4
_store_u32.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int]
_store_u32.restype = None


def default_path() -> str:
    return os.environ.get("RESONA_SHM") or f"/dev/shm/resona-{os.getuid()}"


class SharedState:
    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        self.closed = False
        self._write_lock = threading.Lock()
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.fstat(fd).st_size < SIZE:
                os.ftruncate(fd, SIZE)
            self.mm = mmap.mmap(fd, SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        finally:
            os.close(fd)
        self._address = ctypes.addressof(ctypes.c_char.from_buffer(self.mm))
        self.params = np.ndarray((NPARAMS,), dtype=np.float32, buffer=self.mm, offset=OFF_PARAMS)
        self.corr = np.ndarray((NCORR, 10), dtype=np.float32, buffer=self.mm, offset=OFF_CORR)
        self.ieq = np.ndarray((NBANDS,), dtype=np.float32, buffer=self.mm, offset=OFF_IEQ)
        self.ring_in = np.ndarray((RING,), dtype=np.float32, buffer=self.mm, offset=OFF_RING_IN)
        self.ring_out = np.ndarray((RING,), dtype=np.float32, buffer=self.mm, offset=OFF_RING_OUT)
        if self._u32(OFF_MAGIC) != MAGIC or self._u32(OFF_VERSION) != VERSION:
            self.params[:] = 0
            self.corr[:] = 0
            struct.pack_into("<I", self.mm, OFF_CORR_COUNT, 0)
            struct.pack_into("<I", self.mm, OFF_CONTROL_SEQ, 0)
            struct.pack_into("<I", self.mm, OFF_VERSION, VERSION)
            struct.pack_into("<I", self.mm, OFF_MAGIC, MAGIC)

    def _u32(self, off: int) -> int:
        if self.closed:
            return 0
        return struct.unpack_from("<I", self.mm, off)[0]

    def _bump(self) -> None:
        _store_u32(self._address + OFF_SEQ, (self._u32(OFF_SEQ) + 1) & 0xFFFFFFFF, 0)

    def _publish(self, words: list[tuple[int, int]]) -> None:
        with self._write_lock:
            if self.closed:
                return
            seq = ((self._u32(OFF_CONTROL_SEQ) + 1) | 1) & 0xFFFFFFFF
            _store_u32(self._address + OFF_CONTROL_SEQ, seq, 5)  # sequentially consistent
            for offset, value in words:
                _store_u32(self._address + offset, value, 0)
            self._bump()
            _store_u32(self._address + OFF_CONTROL_SEQ, (seq + 1) & 0xFFFFFFFF, 5)

    # -- UI -> engine -----------------------------------------------------
    def write(self, values: dict[str, float]) -> None:
        if self.closed:
            return
        words = []
        for k, v in values.items():
            i = INDEX.get(k)
            if i is not None:
                bits = struct.unpack("<I", struct.pack("<f", float(v)))[0]
                words.append((OFF_PARAMS + i * 4, bits))
        self._publish(words)

    def write_corr(self, filters: list[dict]) -> None:
        """filters: [{type: 'PK'|..., freq, gain, q} | {type: 'RAW', b0..a2}] (max NCORR)."""
        if self.closed:
            return
        corr = np.zeros((NCORR, 10), dtype=np.float32)
        n = 0
        for f in filters[:NCORR]:
            t = CORR_TYPES.get(str(f.get("type", "PK")).upper(), 0)
            if not t:
                continue
            corr[n] = [t, f.get("freq", 1000), f.get("gain", 0), f.get("q", 0.707),
                            f.get("b0", 1), f.get("b1", 0), f.get("b2", 0), f.get("a1", 0), f.get("a2", 0), 0]
            n += 1
        words = [(OFF_CORR + i * 4, int(v)) for i, v in enumerate(corr.view(np.uint32).flat)]
        words.append((OFF_CORR_COUNT, n))
        self._publish(words)

    # -- engine -> UI -----------------------------------------------------
    @property
    def heartbeat(self) -> int:
        return self._u32(OFF_HEARTBEAT)

    @property
    def sample_rate(self) -> int:
        return self._u32(OFF_RATE) or 48000

    @property
    def out_channels(self) -> int:
        return self._u32(OFF_OUT_CH) or 2

    def meters(self) -> dict[str, float]:
        if self.closed:
            return dict(in_l=0, in_r=0, out_l=0, out_r=0, leveler_db=0, limiter_db=0, loudness_db=0, content_db=0)
        il, ir, ol, orr = struct.unpack_from("<4f", self.mm, OFF_IN_PEAK)
        lev, lim, loud, content = struct.unpack_from("<4f", self.mm, OFF_LEVELER)
        return dict(in_l=il, in_r=ir, out_l=ol, out_r=orr, leveler_db=lev,
                    limiter_db=lim, loudness_db=loud, content_db=content)

    def ieq_gains(self) -> list[float]:
        if self.closed:
            return [0.0] * NBANDS
        return [round(float(x), 2) for x in self.ieq]

    def latest(self, n: int = 2048) -> tuple[np.ndarray, np.ndarray]:
        if self.closed:
            return np.zeros(n, np.float32), np.zeros(n, np.float32)
        pos = self._u32(OFF_RING_POS)
        idx = np.arange(pos - n, pos) % RING
        return self.ring_in[idx].copy(), self.ring_out[idx].copy()

    def close(self) -> None:
        # numpy views do not pin the mapping: drop them and refuse access before unmapping,
        # otherwise a late write after shutdown touches freed memory and segfaults
        with self._write_lock:
            if self.closed:
                return
            self.closed = True
            self.params = self.corr = self.ieq = self.ring_in = self.ring_out = None
            try:
                self.mm.close()
            except (BufferError, ValueError):
                pass
