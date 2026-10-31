#!/bin/sh
# TravelPi power recorder: captures Pi throttle telemetry at boot and detects
# unexpected shutdowns (the loss mode of an undervoltage crash on a Pi Zero 2 W
# single-supply setup, where firmware throttle history resets to 0x0 with power).
set -eu

STATE_DIR=/var/lib/travelpi
STATE_FILE="$STATE_DIR/state.json"
LOG_FILE="$STATE_DIR/power-log.jsonl"
MODE=${1:-start}

mkdir -p "$STATE_DIR"

boot_id() { cat /proc/sys/kernel/random/boot_id 2>/dev/null || echo unknown; }
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
throttled() {
    out=$(vcgencmd get_throttled 2>/dev/null | sed -n 's/^throttled=//p' || true)
    if [ -n "$out" ]; then printf '"%s"' "$out"; else printf 'null'; fi
}
core_volts() {
    out=$(vcgencmd measure_volts core 2>/dev/null | sed -n 's/^volt=\([0-9.]*\)V$/\1/p' || true)
    if [ -n "$out" ]; then printf '%s' "$out"; else printf 'null'; fi
}

case "$MODE" in
stop)
    printf '{"boot_id":"%s","clean":true}\n' "$(boot_id)" > "$STATE_FILE"
    printf '{"t":"%s","event":"clean-shutdown","boot_id":"%s"}\n' "$(now)" "$(boot_id)" >> "$LOG_FILE"
    ;;
*)
    current=$(boot_id)
    # Detect an unexpected shutdown of the previous boot: its state file was
    # never marked clean by the stop hook. Distinct boot ids only; an
    # unresolvable boot id ('unknown') cannot support detection.
    if [ -f "$STATE_FILE" ] && [ "$current" != "unknown" ]; then
        prev_boot=$(sed -n 's/.*"boot_id":"\([^"]*\)".*/\1/p' "$STATE_FILE" | head -1)
        prev_clean=$(sed -n 's/.*"clean":\([a-z]*\).*/\1/p' "$STATE_FILE" | head -1)
        if [ "$prev_boot" != "$current" ] && [ "$prev_clean" != "true" ]; then
            printf '{"t":"%s","event":"unexpected-shutdown","prev_boot_id":"%s"}\n' \
                "$(now)" "$prev_boot" >> "$LOG_FILE"
        fi
    fi
    printf '{"boot_id":"%s","clean":false}\n' "$current" > "$STATE_FILE"
    printf '{"t":"%s","event":"boot","boot_id":"%s","throttled":%s,"core_volts":%s}\n' \
        "$(now)" "$current" "$(throttled)" "$(core_volts)" >> "$LOG_FILE"
    ;;
esac
