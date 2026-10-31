---
title: Radio thermal budget for USB Wi-Fi plus 5GHz AP
labels:
  - ready-for-agent
status: closed
---

## Question

How should Cockpit track the combined thermal load of the Zero 2 W board and its USB MT7921U adapter running hostapd on 5GHz?

Facts (2026-10-26): the AP radio is the USB MT7921U (mt792x_usb, `wlan1`, 5GHz per `reset-travelpi-radios.sh`) on a board with no heatsink; undervoltage and thermal throttling share the `get_throttled` decoder (temperature bits `0x8` now / `0x80`/`0x80000` history — all decoded in `power_status()`; UI shows "Thermal"). Board temperature exists (`measure_temp`/thermal_zone0); the adapter's own temperature and link resets are invisible.

Required outcome:

- Track per-boot temperature trend: max/temp-throttle event count from the decoder history + rolling max board temp in status (`temperature_max_c`, `temp_throttle_events`).
- MT7921 health: detect driver reset/link-down events via journal scan (`mt7921u` probe/reset lines, allowlisted `journalctl` read) → `radio_reset_events`; surface in interface health detail.
- Cockpit health card shows "Radio thermal: N resets · max X°C" with warning state on any thermal-throttle history since boot.
- Advisory copy ties it together: thermal throttle near the brownout threshold means rail demand — reduce AP txpower (already reported as `txpower_dbm`) as the first lever.

Constraints: read-only, additive keys, existing readiness/health payload shapes.

## Comments

- 2026-10-26: 5GHz AP runs through a hub on the same power rail that browns out; decoder groundwork landed in `.scratch/power-supply-indicator/`.
- Live notes: `throttle_events`/`radio_reset_events` from cached kernel-journal scan (60s TTL, timeout-bounded); UI warnings "Radio resets: N". Journal baseline live: 0/0.
- 2026-10-27 incident: MT7921U flapped on the OTG rail (`mt7921u 1-1.2:1.0: vendor request req:63 ... failed:-110` ×4, then full re-probe at 16:30). AP went DOWN with NO-CARRIER while `hostapd.service` reported **active** the whole time — the cockpit cannot see this gap today. Two follow-ups proven by evidence:
  1. Count vendor-request failures (`vendor request` + `failed`) as radio link events, not just lines containing 'reset'.
  2. AP health must come from carrier + associated-station evidence (hostapd log / `ip link` carrier), not the unit's active state.
- 2026-10-27 follow-ups shipped: vendor-request link failures counted as `radio_link_events` (6 live from today 16:30 flap); AP payload gained carrier + stations evidence (`ip link` carrier file + iw station dump); UI overrides an "active" claim with NO CARRIER chip state. Fixtures in tests/frontend-runtime.js cover both directions (no-carrier override, carrier pass-through).
- 2026-10-27 auto-recovery shipped: `travelpi-radio-watch.service` watchdog escalates on sustained no-carrier (~30s): link cycle → USB unbind/bind of the adapter → hostapd restart, with 180s cooldown and per-event journal + `/var/lib/travelpi/radio-recoveries.jsonl` log. Proven live twice: forced no-carrier recovered hands-off, outcome `hostapd-restart` recorded; cockpit health shows watchdog armed, recovery count + last timestamp. Unit has NO BindsTo on hostapd — the first live test showed BindsTo killed the watchdog mid-recovery. Heartbeat touched at every ladder stage (recovery ladder can legitimately run ~170s through a USB probe storm; helper TTL is 180s).
