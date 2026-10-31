# ADR 0004: Radio repair to canonical is allowed; radio role choice stays gated

## Status

Accepted. Extends ADR-0002.

## Decision

Two different operations touch the radio pair and are governed differently:

- **Role swap (`wan_flip`)** — choosing an arbitrary radio as WAN. Gated: the mutation coordinator marks it `available: false`, `describe()` refuses it, and the helper refuses with `unavailable` unless readiness reports `role_switch.available`. ADR-0002's rule holds: no role flip without a verified wired management route and rollback testing.
- **Repair to canonical (`reset_radios`)** — restoring the image's tested layout (AP on the 5 GHz USB radio, hotel station on the internal radio with the required MAC spoof). Available one click, because the target state is the known-good configuration, not a user-chosen topology. It backs up both `hostapd.conf` and the dnsmasq interface config and restores both when `hostapd` fails to come up.

## Rationale

ADR-0002 gates the *choice* of topology because a failed arbitrary swap can orphan the WAN. Repair is the opposite direction: it moves a broken router toward the one configuration the host has been tested in. Refusing repair would leave the operator with the manual root script as the only way out, and the guardrail wants radio recovery to be an explicit human action, not a hidden privileged path.

## Consequences

- The gate for `wan_flip` is enforced in three layers (coordinator descriptor, `describe()`, helper readiness check) and asserted in `tests/mutation-coordinator.js` and `tests/helper-action-contract.py`.
- `reset_radios` stays available and keeps its dual-config restore. Its copy must not promise more than "restore the canonical layout".
- The manual `reset-travelpi-radios.sh` remains a documented human tool and is never invoked by the helper.
- A future verified wired management route is the condition that reopens `wan_flip`; that change must flip readiness evidence, not the UI gate.
