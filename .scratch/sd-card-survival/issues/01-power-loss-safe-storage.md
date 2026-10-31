---
title: SD-card survival for repeated hard power-loss
labels:
  - ready-for-agent
status: closed
---

## Question

What filesystem and logging posture protects the SD card given repeated undervoltage power-loss?

Facts (2026-10-26): the Pi dies by power cut (no clean shutdown) — twice in one session — while writing journald, AdGuard query stats, and Unbound caches to the SD card. The power recorder now flags `unexpected_shutdown`; storage durability is the remaining exposure.

Required outcome:

- journald `Storage=volatile` (size-capped) so steady-state logging never touches the card; last-kernel journal preserved via existing `journalctl -b -1` forensics.
- AdGuard Home stats directory on a tmpfs mount (`stats` path in work dir), filter writes unchanged.
- Mount tuning on the root filesystem for crash safety: ext4 `commit=` reduction documented in deployment; evaluate `data=journal` on metadata-heavy dirs only if benchmarks allow the write penalty on a Zero 2 W.
- Helper reports filesystem health in readiness/status: last mount time, mount state (`filesystems` via `findmnt -T /`), ext4 error count from `dmesg` journal (`EXT4-fs error`), and the recorder's `unexpected_shutdown` count as a composite `storage_risk` level (ok/elevated/high).
- Cockpit surfaces `Storage: elevated risk` with the cause (power-loss count, fs errors).

Constraints: deployment must not brick an active card; every change lands with a documented rollback; helper stays allowlisted.

## Comments

- 2026-10-26: Two hard power-loss events in one day on the same card; recorder proves the pattern will repeat.
- Live notes: journald Storage=volatile deployed (8M runtime cap, MaxFileSec 5min), stale /var/log/journal deleted; AdGuard stats on named tmpfs volume `travelpi-adguard-stats` (size=32M) — quadlet `tmp:` shorthand collided with a pre-existing plain `tmp` volume, so the explicit named tmpfs volume is authoritative. `storage_risk` composite (fs errors > power losses) live at `ok`.
