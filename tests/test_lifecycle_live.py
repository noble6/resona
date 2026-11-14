"""Silent lifecycle stress test. Refuses to run outside tests/run_pipewire.sh."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import wave
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]


def command(*arguments):
    return subprocess.run(arguments, capture_output=True, text=True, check=True, timeout=4).stdout.strip()


def pump(seconds):
    loop = QEventLoop()
    QTimer.singleShot(round(seconds * 1000), loop.quit)
    loop.exec()


def wait_for(condition, message, seconds=12):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump(0.05)
        if condition():
            return
    raise AssertionError(message)


def tone(path, rate, seconds):
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        frames = round(rate * seconds)
        for start in range(0, frames, rate):
            samples = np.arange(start, min(start + rate, frames)) / rate
            audio = np.repeat((0.02 * np.sin(2 * np.pi * 440 * samples))[:, None], 2, axis=1)
            stream.writeframes((audio * 32767).astype("<i2").tobytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soak-seconds", type=float, default=8)
    args = parser.parse_args()
    if not 1 <= args.soak_seconds <= 3600:
        parser.error("--soak-seconds must be between 1 and 3600")
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if (os.environ.get("RESONA_TEST_PRIVATE_SERVER") != "1" or not runtime
            or os.environ.get("PIPEWIRE_RUNTIME_DIR") != runtime
            or os.environ.get("PULSE_SERVER") != f"unix:{runtime}/pulse/native"):
        parser.error("run through tests/run_pipewire.sh; desktop audio must not be used")
    with tempfile.TemporaryDirectory(prefix="resona-lifecycle-", dir=runtime) as directory:
        root = Path(directory)
        os.environ.update(XDG_CONFIG_HOME=str(root / "config"), RESONA_SHM=str(root / "shm"),
                          RESONA_SINK_NAME="resona_lifecycle_sink", RESONA_SCREENSHOT=str(root / "shots"))
        os.environ.pop("RESONA_TEST_TARGET", None)
        sys.path.insert(0, str(ROOT / "app"))
        from resona import hardware, pipeline
        from resona.backend import Backend

        app = QApplication.instance() or QApplication([])
        original = pipeline.default_sink()
        assert original in ("ci_hardware", "ci_other"), "private fixture default is missing"
        outputs = [sink.name for sink in pipeline.list_sinks()]
        assert "ci_hardware" in outputs and "ci_other" in outputs
        backend = Backend()
        processes, players, modules = [], [], []

        def ready(target):
            wait_for(lambda: backend.running and not backend.busy and backend.pipe.target == target,
                     f"engine did not settle on {target}: {backend.pipe.last_log()}")
            wait_for(lambda: pipeline.default_sink() == pipeline.SINK_NAME, "virtual sink did not reclaim default")
            processes.append(backend.pipe.proc)

        def play(path):
            player = subprocess.Popen(["paplay", "-d", pipeline.SINK_NAME, str(path)],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            players.append(player)
            return player

        def healthy():
            assert backend.pipe.running and backend.running and not backend.busy
            assert np.isfinite(list(backend.shm.meters().values())).all(), "non-finite meter values"
            for audio in backend.shm.latest(512):
                assert np.isfinite(audio).all(), "non-finite ring-buffer samples"

        def check_audio():
            path = root / "short.wav"
            tone(path, 48000, 0.5)
            before = backend.shm.heartbeat
            player = play(path)
            wait_for(lambda: backend.shm.heartbeat != before, "audio processing stalled", seconds=3)
            wait_for(lambda: player.poll() is not None, "short player did not finish", seconds=3)
            assert player.returncode == 0, player.stderr.read().decode()
            healthy()

        try:
            ready(original)
            assert hardware.HIRES_CONF.is_relative_to(root), "hardware settings are not private"
            assert all(path.is_relative_to(root) for path in hardware.RESAMPLE_CONFS)
            assert hardware.set_hires(True, 96000) == [44100, 48000, 88200, 96000]
            pump(0.2)
            command("pactl", "info")
            print("  ok   private Hi-Res enable", flush=True)
            assert hardware.hires_enabled()
            assert "96000" in hardware.clock_settings().get("allowed-rates", "")
            assert hardware.set_hires(False) == []
            pump(0.2)
            command("pactl", "info")
            print("  ok   private Hi-Res disable", flush=True)
            assert not hardware.hires_enabled()
            hardware.set_hq_resampler(True)
            assert hardware.hq_resampler_enabled()
            hardware.set_hq_resampler(False)
            assert not hardware.hq_resampler_enabled()
            assert not hardware.set_profile("ci_missing_card", "missing-profile")
            pump(0.2)
            command("pactl", "info")
            print("  ok   private profile rejection", flush=True)
            assert not hardware.bt_switch_codec("ci_missing_card", "missing-codec")
            print("  ok   private hardware settings and rejected commands", flush=True)
            check_audio()
            wait_ready = backend.pipe.wait_ready
            with patch.object(backend.pipe, "wait_ready",
                              side_effect=lambda **kwargs: wait_ready(timeout=0, **kwargs)):
                backend.startEngine()
                failed = backend.pipe.proc
                processes.append(failed)
                wait_for(lambda: not backend.busy and not backend.running,
                         "failed startup did not settle")
            assert failed.poll() is not None, "failed startup left its child engine alive"
            wait_for(lambda: not pipeline.sink_exists(pipeline.SINK_NAME),
                     "failed startup leaked its virtual sink")
            wait_for(lambda: pipeline.default_sink() in outputs,
                     "failed startup did not leave a usable default output")
            backend.setOutput(original)
            ready(original)
            check_audio()
            print("  ok   failed startup cleans up and the same output can retry", flush=True)
            other = "ci_other" if original == "ci_hardware" else "ci_hardware"
            for cycle in range(3):
                for target in (other, original):
                    previous = backend.pipe.proc
                    backend.setOutput(target)
                    ready(target)
                    assert previous.poll() is not None, "previous engine process leaked"
                    check_audio()
                print(f"  ok   output switch cycle {cycle + 1}", flush=True)

            # A second choice while startup is pending must win over the first callback.
            backend.setOutput(other)
            assert backend.busy, "test did not reach an in-flight startup"
            processes.append(backend.pipe.proc)
            backend.setOutput(original)
            ready(original)
            check_audio()
            print("  ok   rapid output choices preserve the last request", flush=True)

            name = "ci_lifecycle_hotplug"
            module = command("pactl", "load-module", "module-null-sink", f"sink_name={name}")
            assert module.isdigit(), "hotplug fixture did not return a module ID"
            modules.append(module)
            wait_for(lambda: pipeline.sink_exists(name), "hotplug fixture did not appear")
            wait_for(lambda: any(sink["name"] == name for sink in backend._sinks),
                     "backend did not discover the new output")
            backend.setOutput(name)
            ready(name)
            check_audio()
            command("pactl", "unload-module", module)
            modules.remove(module)
            wait_for(lambda: backend.running and not backend.busy and backend.pipe.target in outputs,
                     "engine did not recover when output disappeared")
            ready(backend.pipe.target)
            check_audio()
            module = command("pactl", "load-module", "module-null-sink", f"sink_name={name}")
            assert module.isdigit()
            modules.append(module)
            wait_for(lambda: pipeline.sink_exists(name), "returning fixture did not appear")
            wait_for(lambda: any(sink["name"] == name for sink in backend._sinks),
                     "backend did not rediscover the returning output")
            backend.setOutput(name)
            ready(name)
            check_audio()
            backend.setOutput(original)
            ready(original)
            print("  ok   output disappearance and reappearance", flush=True)

            previous = backend.pipe.proc
            previous.kill()
            previous.wait(timeout=3)
            wait_for(lambda: backend.pipe.proc is not previous and backend.running and not backend.busy,
                     "watchdog did not replace the failed engine")
            ready(original)
            check_audio()
            print("  ok   watchdog recovers a killed child engine", flush=True)

            for rate in (44100, 48000, 96000):
                command("pw-metadata", "-n", "settings", "0", "clock.force-rate", str(rate))
                path = root / f"rate-{rate}.wav"
                tone(path, rate, 3)
                player = play(path)
                wait_for(lambda: backend.shm.sample_rate == rate,
                         f"DSP did not adopt private graph rate {rate}", seconds=5)
                wait_for(lambda: player.poll() is not None, "rate-test player did not finish", seconds=5)
                assert player.returncode == 0, player.stderr.read().decode()
                healthy()
                print(f"  ok   private graph rate {rate} Hz", flush=True)
            command("pw-metadata", "-n", "settings", "0", "clock.force-rate", "0")

            path = root / "soak.wav"
            tone(path, 48000, args.soak_seconds + 2)
            player = play(path)
            engine = backend.pipe.proc
            deadline = time.monotonic() + args.soak_seconds
            heartbeat = backend.shm.heartbeat
            last_progress = time.monotonic()
            while time.monotonic() < deadline:
                pump(0.1)
                healthy()
                assert backend.pipe.proc is engine, "engine restarted during sustained processing"
                assert player.poll() is None, "soak stream ended early"
                current = backend.shm.heartbeat
                if current != heartbeat:
                    heartbeat, last_progress = current, time.monotonic()
                assert time.monotonic() - last_progress < 2, "heartbeat stalled during sustained processing"
            player.terminate()
            player.wait(timeout=3)
            print(f"  ok   {args.soak_seconds:g}s sustained processing without stalls or non-finite samples", flush=True)
        finally:
            for player in players:
                if player.poll() is None:
                    player.terminate()
                    player.wait(timeout=3)
                if player.stderr is not None:
                    player.stderr.close()
            restore = backend.pipe.target
            backend.shutdown()
            command("pw-metadata", "-n", "settings", "0", "clock.force-rate", "0")
            for module in modules:
                command("pactl", "unload-module", module)
            assert all(process is not None and process.poll() is not None for process in processes), "engine process leaked on quit"
            assert not pipeline.sink_exists(pipeline.SINK_NAME), "virtual sink leaked on quit"
            if restore and pipeline.sink_exists(restore):
                assert pipeline.default_sink() == restore, "active output not restored on quit"
            pipeline.set_default_sink(original)
        print("LIFECYCLE STRESS PASSED", flush=True)


if __name__ == "__main__":
    main()
