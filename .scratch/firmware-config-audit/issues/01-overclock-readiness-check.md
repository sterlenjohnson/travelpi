---
title: Firmware config audit for brownout-inducing settings
labels:
  - ready-for-agent
status: closed
---

## Question

How should readiness flag firmware settings that raise 5V-rail demand on this marginal dual-supply board?

Facts (2026-10-26): Zero 2 W browns out on one supply under load. Overclock/clock settings in `/boot/firmware/config.txt` (`over_voltage`, `arm_freq`, `core_freq`, `sdram_freq`) directly raise rail demand and are classic brownout triggers; today the cockpit has no visibility into them.

Required outcome:

- Helper parses `/boot/firmware/config.txt` (read-only) and reports `firmware_overrides` — the non-default voltage/frequency settings found.
- Readiness entry `firmware-config` marks `ok` when stock settings, `elevated` when any over-voltage/overclock keys are present, listing them.
- Cockpit health detail surfaces "Firmware overclock settings present: <keys>" as an advisory (no mutation, no recommendation engine — advisory only).
- Audit is a strict allowlist of keys; never exposes the whole file to the browser.

Constraints: additive payload + readiness shape parity with existing readiness evidence.

## Comments

- 2026-10-26: Board dies on single supply under current load; firmware clocking is the main tunable rail-demand knob.
- Live notes: readiness `firmware: ok` (overrides `[]`); allowlist-only parse (11 voltage/frequency keys), comments stripped. Current board is stock-clocked.
