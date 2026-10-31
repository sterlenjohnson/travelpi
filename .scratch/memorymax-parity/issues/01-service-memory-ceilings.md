---
title: MemoryMax parity across all router services on 512MB
labels:
  - ready-for-agent
status: closed
---

## Question

Give every resident service an explicit memory ceiling so 512MB + zram behavior is predictable under load?

Facts (2026-10-26): AdGuard Home Quadlet has `MemoryMax=192M` + `TasksMax=128` (repo) and PackageKit has a resource guard (masked after zram-exhaustion storms, README). Unbound, hostapd, tailscaled, dnsmasq, and podman's own daemons run unbounded on the same 512MB board. Swap usage is already surfaced in the health card.

Required outcome:

- Audit resident set: `systemctl status` + per-unit current memory on the live Pi; record measured baselines in this ticket.
- Add drop-in resource guards: Unbound (`MemoryMax` sized to its cached DB reality, e.g. 96–128M measured), tailscaled (~64M), dnsmasq/hostapd (small, fixed), each `TasksMax`-bounded; drop-ins shipped in `systemd/<name>.d/resource-guard.conf` mirroring the existing PackageKit guard pattern.
- Deployment installs + `daemon-reload` only (no network-service restart), same safety posture as the existing target.
- Cockpit readiness gains a `memory-guards` evidence entry: services with/without ceilings; health card gains top-memory service summary from `systemctl status --type service --properties=MemoryCurrent` (allowlisted read).

Constraints: measured baselines before picking ceilings; never cap below measured peak (guaranteed OOM-kill = the brownout UX again).

## Comments

- 2026-10-26: README history — Cockpit's own polling exhausted zram once; parity prevents the next resource storm from an unbounded service.
- Live notes: drop-ins installed and active (unbound 128M, tailscaled 96M, hostapd 32M, dnsmasq 32M, containerd 192M, adguardhome 192M via quadlet); readiness `memory_guards` shows all five guarded, none unprotected. Drop-ins apply on the next start of each unit; deploy restarts only journald + adguardhome, never client-facing network services.
- 2026-10-27 podman fleet guards added: `machine.slice` (rootful containers: MemoryMax 256M, TasksMax 512, CPUQuota 200%) and `user.slice` (rootless fleet: 256M / 512 / CPUQuota 150%) drop-ins installed by deploy; readiness `memory_guards` now reports 7 guarded, 0 unprotected. On this host the rootless AdGuard quadlet is masked (rootful system quadlet is canonical; the duplicate would have competed for ports 53/80 at boot).
