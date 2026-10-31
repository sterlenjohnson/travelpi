---
title: Power-gated staged service startup
labels:
  - needs-triage
status: closed
---

## Question

Should the heavy DNS stack defer startup until the 5V rail proves healthy, to avoid brownouts at boot inrush?

Facts (2026-10-26): the Zero 2 W dies on a single supply under load; boot is peak inrush (AdGuard container spin-up, Unbound priming, hostapd + USB radio enumeration, Tailscale handshake all at once). The recorder + decoder now expose a per-boot power signal within seconds of start.

Design question:

- Boot order: radio/AP + DHCP first (client connectivity = user can reach the dashboard and see the power indicator), then gate `adguardhome.service` (and optionally `unbound`) on a cheap early "power-good" check: `get_throttled == 0x0` after a settle window, retried with backoff.
- Gating mechanism candidates: systemd unit ordering + a `ConditionPathExists`-style marker written by the recorder script's boot sample; Quadlet `ExecStartPre` probe (rootful unit); systemd `ExecStartPre` sleep-and-check loop with bounded retries.
- Fallback: bounded deferral (e.g. start anyway after 120s) so a marginal supply never deadlocks the DNS stack permanently; cockpit surfaces "DNS stack deferred: power signal" state.
- Must interlock with `.scratch/adguard-offline-images/` (no network-coupled startup work in the deferred window).

This is a design decision (gating criteria, deferral bound, failure semantics) — evaluate against measured inrush data once INA219 lands; prototype the marker-based gate first.

## Comments

- 2026-10-26: Two boot/load brownouts observed; power decoder + recorder exist as the gating signal source.
- Resolution: bounded gate shipped as `/usr/local/libexec/travelpi-power-gate` (ExecStartPre on adguardhome; defers while `get_throttled != 0x0`, 120s hard bound, always starts after; TimeoutStartSec=240). Interlock with offline images honored (no network in the gate).
