#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
HELPER="$ROOT/helper/travelpi-cockpit"

invalid=$($HELPER invalid-command 2>/dev/null || true)
printf '%s\n' "$invalid" | grep -q '"code":"invalid_command"'

profiles=$($HELPER profiles 2>/dev/null || true)
printf '%s\n' "$profiles" | grep -q '"code":"invalid_command"'

# The unprivileged refusal needs a non-root caller; as root this would really
# run the action, so it is skipped here and pinned through the EUID seam in
# tests/privilege-gate.py.
if [ "$(id -u)" != 0 ]; then
vpn=$(printf '%s\n' '{"action":"vpn_toggle","provider":"tailscale","enabled":false,"confirm":true}' | "$HELPER" action 2>/dev/null || true)
printf '%s\n' "$vpn" | grep -q 'not_privileged'
fi

printf '%s\n' 'helper contract checks passed'
