---
title: Clock-sync readiness gate after power loss
labels:
  - ready-for-agent
status: closed
---

## Question

How should TravelPi detect and gate on an unsynchronized clock following hard power-loss?

Facts (2026-10-26): the Pi runs `fake-hwclock` (`journalctl -b -1` showed timestamps from months earlier after a power-loss boot). Every crash leaves the clock wrong until NTP completes, which poisons TLS validation, AdGuard filter updates, DNSSEC/upstream TLS timing, and log forensics — exactly the window when the user is diagnosing the crash.

Required outcome:

- Helper reports `clock_synced` (systemd-timesyncd `NTP` state via `timedatectl show --property=NTPSynchronized` — allowlisted read) plus `clock_epoch` for the UI.
- Cockpit Quick Settings surfaces a `Clock unsynced` chip/detail after boot until sync; health warnings gain "Clock unsynced" so users don't chase phantom DNS/TLS failures.
- AdGuard filter-update and any TLS-verifying helper actions defer (or warn) while unsynced; the cockpit surfaces "stale filters: clock unsynced" rather than silently failing.
- Readiness evidence gains a `clock` entry consistent with the existing readiness shape.

Constraints: additive payload, no new mutation actions, allowlisted helper commands only.

## Comments

- 2026-10-26: Observed post-crash boot with journal timestamps ~11 months in the past.
- Live notes: `clock_synced: true` via timedatectl allowlisted read (None on unresolvable — degrades explicitly, never faked). UI warning "Clock unsynced (NTP pending)". Readiness covers today.
