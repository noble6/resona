"""Live PipeWire integration test. Silent: the engine is routed into temporary null sinks.

    python3 tests/test_pipewire.py
Covers: stereo passthrough, live parameter changes, the 5.1 upmix graph on a real
6-channel sink, live correction-EQ upload, and the convolver (true-stereo IR) graph.
"""
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from resona import correction, hardware, pipeline, shm  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="resona-it-"))
FS = 48000
fails = 0


def check(ok, msg):
    global fails
    print(("  ok   " if ok else "  FAIL ") + msg)
    fails += not ok


def write_wav(path, x, ch=2, fs=FS, float32=False):
    x = np.asarray(x)
    if float32:  # minimal IEEE-float WAV writer (IRS files are usually float)
        data = x.astype("<f4").tobytes()
        hdr = b"RIFF" + (36 + len(data)).to_bytes(4, "little") + b"WAVEfmt " + (16).to_bytes(4, "little")
        hdr += (3).to_bytes(2, "little") + ch.to_bytes(2, "little") + fs.to_bytes(4, "little")
        hdr += (fs * ch * 4).to_bytes(4, "little") + (ch * 4).to_bytes(2, "little") + (32).to_bytes(2, "little")
        Path(path).write_bytes(hdr + b"data" + len(data).to_bytes(4, "little") + data)
        return
    with wave.open(str(path), "wb") as w:
        w.setnchannels(ch); w.setsampwidth(2); w.setframerate(fs)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def tone(path, f, amp, secs=2.0):
    t = np.arange(int(FS * secs)) / FS
    write_wav(path, np.repeat(amp * np.sin(2 * np.pi * f * t), 2))


def capture_while_playing(play_sink, rec_source, wav, ch=2):
    out = TMP / "rec.raw"
    rec = subprocess.Popen(["parecord", "-d", rec_source, "--raw", "--format=float32le",
                            "--rate=48000", f"--channels={ch}", str(out)])
    time.sleep(0.4)
    subprocess.run(["paplay", "-d", play_sink, str(wav)], check=True)
    time.sleep(0.3)
    rec.terminate(); rec.wait()
    return np.fromfile(out, dtype="<f4").reshape(-1, ch)


def null_sink(name, chmap=None):
    args = ["pactl", "load-module", "module-null-sink", f"sink_name={name}"]
    if chmap:
        args += [f"channels={len(chmap.split(','))}", f"channel_map={chmap}"]
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()


def fresh(pipe, target, **kw):
    ok = pipe.start(target, make_default=False, **kw) if not kw else (pipe.spawn(target, **kw) or pipe.wait_ready(False))
    time.sleep(0.6)  # let WirePlumber restore any saved volume, then override it
    subprocess.run(["pactl", "set-sink-volume", pipe.sink_name, "100%"])
    time.sleep(0.2)
    return ok


mods = [null_sink("resona_it_null"),
        null_sink("resona_it_51", "front-left,front-right,front-center,lfe,rear-left,rear-right")]
state = shm.SharedState(str(TMP / "shm"))
pipe = pipeline.Pipeline(state.path, sink_name="resona_it_sink", out_name="resona_it_out",
                         description="Resona Integration Test")
NEUTRAL = {k: 0 for k in shm.PARAMS}
NEUTRAL.update(enable=1, eq_on=1, stage_width=1, bass_freq=100, lev_target=-16, lim_on=1, lim_ceil=-0.5,
               amb_size=.4, amb_damp=.5, hrtf_angle=30)
try:
    state.write(NEUTRAL)
    state.write_corr([])
    ok = fresh(pipe, "resona_it_null")
    check(ok, f"stereo filter-chain sink came up {pipe.last_log().strip()[-200:]!r}")
    if not ok:
        raise SystemExit(1)
    hb0 = state.heartbeat
    wav = TMP / "tone.wav"
    tone(wav, 1000, 0.25)
    x = capture_while_playing("resona_it_sink", "resona_it_null.monitor", wav)
    peak = np.abs(x).max()
    check(state.heartbeat > hb0, f"engine is processing (rate {state.sample_rate}, {state.out_channels} ch out)")
    check(abs(20 * np.log10(peak / 0.25)) < 0.5, f"neutral passthrough: {20*np.log10(peak):.2f} dBFS (expected -12.04)")

    state.write({"eq5": 9})
    time.sleep(0.2)
    x = capture_while_playing("resona_it_sink", "resona_it_null.monitor", wav)
    peak2 = np.abs(x[len(x)//4: -len(x)//4]).max()
    check(abs(20*np.log10(peak2/peak) - 9) < 0.6, f"live EQ change: +{20*np.log10(peak2/peak):.2f} dB (expected +9)")
    state.write({"eq5": 0})

    # correction EQ uploaded live (AutoEq-format text)
    pre, filters = correction.parse_parametric("Preamp: -2 dB\nFilter 1: ON PK Fc 1000 Hz Gain 6 dB Q 1.0\n")
    state.write_corr(filters)
    state.write({"corr_on": 1, "corr_preamp": pre})
    time.sleep(0.2)
    x = capture_while_playing("resona_it_sink", "resona_it_null.monitor", wav)
    g = 20 * np.log10(np.abs(x[len(x)//4: -len(x)//4]).max() / peak)
    check(abs(g - 4) < 0.6, f"AutoEq-format correction applied live: {g:+.2f} dB (expected +4)")
    state.write({"corr_on": 0})
    pipe.stop(restore_default=False)

    # 5.1 upmix on a real 6-channel sink
    lay = hardware.layout_of(pipeline.sink_channel_map("resona_it_51"))
    check(lay["channels"] == 6 and lay["bits"] == 1 | 2 | 8, f"detected target layout {lay['name']} {lay['positions']}")
    state.write({"upmix_on": 1, "upmix_center": 1, "upmix_surr": 1, "upmix_lfe": 1, "layout": lay["bits"]})
    ok = fresh(pipe, "resona_it_51", layout=lay)
    check(ok, f"surround graph came up {pipe.last_log().strip()[-200:]!r}")
    tone(wav, 440, 0.25)
    x = capture_while_playing("resona_it_sink", "resona_it_51.monitor", wav, ch=6)
    check(state.out_channels == 8, "8-output resona_surround engine instantiated by PipeWire")
    x = x[len(x)//4: -len(x)//4]
    r = np.sqrt((x ** 2).mean(axis=0)) + 1e-9
    check(r[2] > 3 * r[0], f"centred tone steered to FC: FC {20*np.log10(r[2]):.1f} dBFS vs FL {20*np.log10(r[0]):.1f} dBFS")
    pipe.stop(restore_default=False)

    # convolver (true-stereo float IR) in front of the engine
    n = 4800
    ir = np.zeros((n, 4))
    ir[0, 0] = ir[0, 3] = 1.0                           # direct L→L, R→R
    ir[240:, :] += np.random.default_rng(1).standard_normal((n - 240, 4)) * 0.02 * np.exp(-np.arange(n - 240) / 900)[:, None]
    write_wav(TMP / "room.irs", ir.reshape(-1), ch=4, float32=True)
    info = correction.read_ir(str(TMP / "room.irs"))
    check(info["channels"] == 4 and info["frames"] == n, f"IRS parsed: {info['channels']} ch, {info['seconds']} s, gain {info['gain']:.3f}")
    state.write({"layout": 0})
    ok = fresh(pipe, "resona_it_null", ir=dict(info, mix=1.0))
    check(ok, f"convolver graph came up {pipe.last_log().strip()[-300:]!r}")
    tone(wav, 1000, 0.25)
    x = capture_while_playing("resona_it_sink", "resona_it_null.monitor", wav)
    lvl = 20 * np.log10(np.abs(x[len(x)//4: -len(x)//4]).max() + 1e-9)
    check(-20 < lvl < -6, f"audio flows through the convolver ({lvl:.1f} dBFS)")
finally:
    pipe.stop(restore_default=False)
    for m in mods:
        subprocess.run(["pactl", "unload-module", m])
    check(not pipeline.sink_exists("resona_it_sink"), "engine sink removed after stop")
    print("ALL PASSED" if not fails else f"FAILED ({fails})")
