"""Shared-memory bridge to the DSP engine (mirror of engine/resona_shm.h, v2).

Offsets are asserted against the C layout printed by `make -C engine test`.
"""
from __future__ import annotations

import mmap
import os
import struct

import numpy as np

MAGIC = 0x414E5352
VERSION = 2
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
]
INDEX = {n: i for i, n in enumerate(PARAMS)}

# correction filter types (engine CORR_*)
CORR_TYPES = {"OFF": 0, "PK": 1, "LSC": 2, "HSC": 3, "LP": 4, "HP": 5, "RAW": 6}


def default_path() -> str:
    return os.environ.get("RESONA_SHM") or f"/dev/shm/resona-{os.getuid()}"


class SharedState:
    def __init__(self, path: str | None = None):
        self.path = path or default_path()
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if os.fstat(fd).st_size < SIZE:
                os.ftruncate(fd, SIZE)
            self.mm = mmap.mmap(fd, SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
        finally:
            os.close(fd)
        self.params = np.ndarray((NPARAMS,), dtype=np.float32, buffer=self.mm, offset=OFF_PARAMS)
        self.corr = np.ndarray((NCORR, 10), dtype=np.float32, buffer=self.mm, offset=OFF_CORR)
        self.ieq = np.ndarray((NBANDS,), dtype=np.float32, buffer=self.mm, offset=OFF_IEQ)
        self.ring_in = np.ndarray((RING,), dtype=np.float32, buffer=self.mm, offset=OFF_RING_IN)
        self.ring_out = np.ndarray((RING,), dtype=np.float32, buffer=self.mm, offset=OFF_RING_OUT)
        if self._u32(OFF_MAGIC) != MAGIC or self._u32(OFF_VERSION) != VERSION:
            self.params[:] = 0
            self.corr[:] = 0
            struct.pack_into("<I", self.mm, OFF_CORR_COUNT, 0)
            struct.pack_into("<I", self.mm, OFF_VERSION, VERSION)
            struct.pack_into("<I", self.mm, OFF_MAGIC, MAGIC)

    def _u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.mm, off)[0]

    def _bump(self) -> None:
        struct.pack_into("<I", self.mm, OFF_SEQ, (self._u32(OFF_SEQ) + 1) & 0xFFFFFFFF)

    # -- UI -> engine -----------------------------------------------------
    def write(self, values: dict[str, float]) -> None:
        for k, v in values.items():
            i = INDEX.get(k)
            if i is not None:
                self.params[i] = float(v)
        self._bump()

    def write_corr(self, filters: list[dict]) -> None:
        """filters: [{type: 'PK'|..., freq, gain, q} | {type: 'RAW', b0..a2}] (max NCORR)."""
        self.corr[:] = 0
        n = 0
        for f in filters[:NCORR]:
            t = CORR_TYPES.get(str(f.get("type", "PK")).upper(), 0)
            if not t:
                continue
            self.corr[n] = [t, f.get("freq", 1000), f.get("gain", 0), f.get("q", 0.707),
                            f.get("b0", 1), f.get("b1", 0), f.get("b2", 0), f.get("a1", 0), f.get("a2", 0), 0]
            n += 1
        struct.pack_into("<I", self.mm, OFF_CORR_COUNT, n)
        self._bump()

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
        il, ir, ol, orr = struct.unpack_from("<4f", self.mm, OFF_IN_PEAK)
        lev, lim, loud, content = struct.unpack_from("<4f", self.mm, OFF_LEVELER)
        return dict(in_l=il, in_r=ir, out_l=ol, out_r=orr, leveler_db=lev,
                    limiter_db=lim, loudness_db=loud, content_db=content)

    def ieq_gains(self) -> list[float]:
        return [round(float(x), 2) for x in self.ieq]

    def latest(self, n: int = 2048) -> tuple[np.ndarray, np.ndarray]:
        pos = self._u32(OFF_RING_POS)
        idx = np.arange(pos - n, pos) % RING
        return self.ring_in[idx].copy(), self.ring_out[idx].copy()

    def close(self) -> None:
        try:
            self.mm.close()
        except (BufferError, ValueError):
            pass
