#!/bin/sh
# Bounded power gate (travelpi-power-gate): AdGuard Home startup defers while the
# 5V rail reports throttle/undervoltage flags, and starts unconditionally after
# the deferral bound so a marginal supply never deadlocks the DNS stack.
# Field evidence: Pi Zero 2 W dies on a single supply under load; boot is peak
# inrush. get_throttled == 0x0 means the rail is clean right now.
BOUND_SECONDS=120
elapsed=0
while [ "$elapsed" -lt "$BOUND_SECONDS" ]; do
    # Strip 0x prefix and leading zeros: empty result means every flag bit is clear
    # (also covers telemetry unavailable), any residue defers this pass.
    flags=$(vcgencmd get_throttled 2>/dev/null | sed -n 's/^throttled=0x//p' | sed 's/^0*//')
    if [ -z "$flags" ]; then
        exit 0
    fi
    sleep 5
    elapsed=$((elapsed + 5))
done
exit 0
