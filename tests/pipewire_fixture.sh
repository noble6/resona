#!/bin/bash
# Private-server fixture creation can race PipeWire/WirePlumber initialization.
wait_for_test_sink() {
    local name="$1" seconds="${2:-10}" loaded=0
    local deadline=$((SECONDS + seconds))
    while (( SECONDS < deadline )); do
        if timeout 2 pactl list short sinks 2>/dev/null |
                awk -v wanted="$name" '$2 == wanted { found=1 } END { exit !found }'; then
            return 0
        fi
        if (( !loaded )); then
            if timeout 2 pactl load-module module-null-sink "sink_name=$name" \
                    >/dev/null 2>"$runtime/fixture-$name.log"; then
                loaded=1
            fi
        fi
        sleep 0.1
    done
    echo "Private test sink $name did not become ready within $seconds seconds" >&2
    return 1
}
