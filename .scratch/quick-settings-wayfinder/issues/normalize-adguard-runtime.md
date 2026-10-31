---
title: Normalize AdGuard runtime for stealth mode
labels:
  - wayfinder:task
status: closed
parent: ../map.md
blocks:
  - choose-encrypted-dns-policy.md
  - prototype-quick-settings-surface.md
---

## Question

What exact runtime and filesystem layout should the stealth script use to start, stop, and health-check the configured AdGuard Home instance on the Pi Zero 2 W?

Facts to resolve:

- `the activation script` invokes `podman compose up -d` from `~/adguard`.
- The configuration exists, but the service was observed stopped.
- The compose file and volume paths must be reconciled with the actual container runtime.
- AdGuard should remain behind an allowlisted helper action, not arbitrary GUI shell execution.

The answer must define the authoritative start command, service/container health check, port ownership, rollback behavior, and how the UI reports configured/stopped/running/error.

## Resolution

Keep the rootless Podman Compose project at `~/adguard` with the authoritative configuration and work directories at `~/adguard/{conf,work}`. The previous compose file incorrectly mounted nested `~/adguard/adguard/{conf,work}` paths, so it was corrected to explicit top-level mounts. The current failure was also a port collision: dnsmasq owned TCP/UDP port 53 on `192.168.200.1` while AdGuard Home uses host networking and requires port 53.

The runtime decision is:

- Unbound remains recursive DNS on `127.0.0.1:5335`.
- dnsmasq remains DHCP-only with `port=0` and continues advertising `192.168.200.1` as DNS through DHCP option 6.
- AdGuard Home owns LAN DNS on port 53 and forwards to Unbound.
- The stealth script remains the activation entry point but must use the fixed compose project, surface start failures, and verify the AdGuard container plus port 53 after startup.
- The helper should expose configured/running/stopped/error and fixed start/stop/restart actions; it must not expose compose or shell arguments.

The Pi runtime has now been corrected and verified: dnsmasq uses `port=0`, Unbound listens on `127.0.0.1:5335`, AdGuard owns port 53, the corrected compose project starts the container, and the rootless Podman restart unit is enabled. The stealth-script health-check follow-up remains a separate implementation task.
