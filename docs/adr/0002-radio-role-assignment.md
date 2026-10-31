# ADR 0002: Radio role assignment is real but not auto-applied

## Status

Accepted.

## Decision

Treat radio role assignment (choosing which detected WiFi radio is WAN/STA and which are LAN/AP, one WAN plus one-or-more LAN, selected from a menu of radio hardware names) as a first-class domain concept.

The action is gated on readiness evidence: it is only available when two or more WiFi radios are detected. The WAN (STA) radio retains its MAC identity under the WAN identity policy.

A safe role swap requires a verified LAN uplink. Until the backend supports a safe swap, the action is surfaced as unavailable through the mutation coordinator's normal `request` path rather than staging a command the coordinator cannot execute.

## Rationale

The onboard radio of a low-power Pi (e.g. Zero 2 W) cannot associate to some hotel networks (protocol incompatibility), so the USB WiFi is used as WAN and the onboard radio as LAN. This is a real, repeated workaround, not dead code. Encoding it as a real coordinator action keeps the seam authoritative and avoids a hyphenated pseudo-command that bypasses the coordinator.

But automating the swap is unsafe without a connected LAN uplink: a failed swap can orphan the WAN. So the concept is modelled honestly (available when ≥2 radios, STA-WAN keeps MAC identity) while execution stays unavailable until the backend can perform it safely.

## Consequences

- The mutation coordinator owns radio role assignment as an `available: false` action keyed on detected radios; the UI lists hardware names from the radio inventory.
- `travelpi.ts` must not stage a `"wan-flip"` pseudo-command or special-case it to a no-op; it routes through `request` like every other action.
- Future architecture reviews should not re-suggest auto-flipping roles; the gating and MAC-identity retention are intentional.

## Reopens

ADR-0001 only (no conflict): WAN identity remains governed by the WAN identity policy; credentials stay with NetworkManager.
