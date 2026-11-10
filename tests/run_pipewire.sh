#!/bin/bash
# Run live tests against a private audio server, never the desktop session.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" != --session ]]; then
    exec dbus-run-session -- bash "$0" --session
fi

runtime=$(mktemp -d "${TMPDIR:-/tmp}/resona-tests.XXXXXX")
export XDG_RUNTIME_DIR="$runtime"
export XDG_CONFIG_HOME="$runtime/config"
export XDG_STATE_HOME="$runtime/state"
export XDG_CACHE_HOME="$runtime/cache"
export XDG_DATA_HOME="$runtime/data"
export PIPEWIRE_RUNTIME_DIR="$runtime"
export PIPEWIRE_REMOTE=pipewire-0
export PULSE_SERVER="unix:$runtime/pulse/native"
export QT_QPA_PLATFORM=offscreen
unset PIPEWIRE_CONFIG_DIR PIPEWIRE_CONFIG_NAME PULSE_CLIENTCONFIG
mkdir -p "$XDG_CONFIG_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME"
pids=()
cleanup() {
    rc=$?
    if (( rc != 0 )); then cat "$runtime"/*.log >&2 || true; fi
    if (( ${#pids[@]} )); then
        kill "${pids[@]}" 2>/dev/null || true
        wait "${pids[@]}" 2>/dev/null || true
    fi
    rm -rf "$runtime"
    exit "$rc"
}
trap cleanup EXIT

# Disable hardware discovery for both WirePlumber 0.4 and 0.5.
mkdir -p "$XDG_CONFIG_HOME/wireplumber/"{wireplumber.conf.d,main.lua.d,bluetooth.lua.d}
cat > "$XDG_CONFIG_HOME/wireplumber/wireplumber.conf.d/99-resona-test.conf" <<'CONF'
wireplumber.profiles = {
  main = {
    monitor.alsa = disabled
    monitor.bluez = disabled
    monitor.bluez-midi = disabled
  }
}
CONF
echo 'alsa_monitor.enabled = false' > "$XDG_CONFIG_HOME/wireplumber/main.lua.d/99-resona-test.lua"
echo 'bluez_monitor.enabled = false' > "$XDG_CONFIG_HOME/wireplumber/bluetooth.lua.d/99-resona-test.lua"

pipewire > "$runtime/pipewire.log" 2>&1 & pids+=("$!")
for (( i=0; i<100; i++ )); do
    [[ -S "$runtime/pipewire-0" ]] && break
    sleep 0.1
done
[[ -S "$runtime/pipewire-0" ]]
pipewire-pulse > "$runtime/pulse.log" 2>&1 & pids+=("$!")
wireplumber > "$runtime/wireplumber.log" 2>&1 & pids+=("$!")
for (( i=0; i<100; i++ )); do
    pactl info >/dev/null 2>&1 && break
    sleep 0.1
done
pactl info >/dev/null
pactl load-module module-null-sink sink_name=ci_hardware >/dev/null
pactl load-module module-null-sink sink_name=ci_other >/dev/null
pactl set-default-sink ci_hardware

python3 tests/test_pipewire.py
python3 tests/test_capture_live.py
python3 tests/test_routing_live.py

RESONA_SCREENSHOT="$runtime/screenshots" RESONA_SHM="$runtime/ui-shm" \
    RESONA_TEST_TARGET=ci_hardware python3 "${RESONA_TEST_APP:-app/main.py}" > "$runtime/ui.log" 2>&1
if grep -E 'qml:|Error:' "$runtime/ui.log"; then
    exit 1
fi
