---
title: Surface power-supply state prominently for Pi Zero 2 W
labels:
  - needs-triage
status: closed
---

## Question

How should TravelPi Cockpit surface power-supply health so a Pi Zero 2 W that cannot boot on a single source is detected quickly, at boot and in the dashboard?

Facts to resolve:

- The hardware fails to boot reliably without two power sources; instability appears as undervoltage events.
- The helper already reads `vcgencmd get_throttled` in `power_status()` (`helper/travelpi-cockpit`) and the status payload includes `power` with temperature, throttle flags, and a detail string.
- The dashboard shows power throttling only as a minor line in the Quick Settings health block (`index.html`, `quick-health-detail`); it is not an at-a-glance indicator.
- `get_throttled` is a bitmask: the low nibble is the current throttling reason (bit 0 = currently under-voltage, bit 3 = currently thermally throttled), and the high word (e.g. `0x10000`) records under-voltage history since boot. History is the critical signal for this hardware: the current flag can be clear at the time of viewing while under-voltage events caused earlier boot failures.

Required outcome:

- The helper decodes `get_throttled` into structured fields (`under_volt_now`, `under_volt_history`, `throttled_now`, `temp_throttle`, raw hex) instead of only a generic "flags present" detail.
- The Quick Settings surface shows a dedicated power indicator (OK / under-voltage now / under-voltage history / telemetry unavailable) with the raw hex available for diagnosis, styled as a warning state when history is present.
- A boot-time record of the throttled value is written early (journal entry in the existing helper/deployment units) so intermittent boot failures can be diagnosed after the fact.
- The indicator is read-only; it adds no new mutation actions and stays within the existing helper allowlist.

Constraints:

- No new privileges, units, or shell fragments exposed to the browser.
- Keep the payload contract additive so existing UI builds tolerate the new fields.
- Labels shown must reflect verified evidence (`vcgencmd` output), not inferred state.

## Comments

- 2026-10-26: Reported from the field — a Pi Zero 2 W will not boot without two power sources; AdGuard/DNS stack confirmed running (AdGuard Home → Unbound on `127.0.0.1:5335`). Power visibility is the requested follow-up.
- 2026-10-26 hardware survey on the live Pi Zero 2 W (Rev 1.0, firmware Aug 2025):
  - `vcgencmd get_throttled` → `0x0` (clean right now; history resets each boot, so per-boot capture is required to catch boot-blocking events).
  - `vcgencmd measure_volts core` works (measured `1.2563V`). `measure_volts 5V`, `sdram`, `cpucpu`, and `vsense` are **not supported** on this board.
  - No `/sys/class/power_supply` entries; no onboard current sensor. True current draw requires an external INA219/INA226 on I2C (exposes `/sys/class/hwmon/*/name` = `ina219`, `in2_input` µA, `power1_input` mW). The UI must show current as optional.
  - Dual-USB confirmed in software: the OTG port runs as a DWC2 host (`/sys/bus/usb/devices/usb1` = "DWC OTG Controller") powering the MT7921 USB Wi-Fi adapter through a hub; the PWR port is the second feed. Cockpit can show OTG host state and connected device count as the USB-port evidence.
- Implementation in progress (worker fan-out): helper decodes throttle bits into structured fields (`signal`, `under_volt_now/history`, `throttle_*`, `core_volts`, `current_ma`/`power_w` when a sensor exists, `usb_otg_present`/`usb_devices`); the Quick Settings "Pi health" card gains a dedicated power indicator with warning state on undervoltage history.
- 2026-10-26 field event: one of the two power sources was removed while running — **the Pi died immediately**. Confirms the single supply cannot sustain the board under load.
- Critical design consequence: `get_throttled` history lives in volatile firmware state and is **lost on power loss**. A cockpit indicator that only reports current/boot-local flags will show a clean slate after the very crash it is meant to warn about. Required addition: the helper persists each telemetry sample (throttle bits, core volts, boot marker) to a small file under `/var/lib/travelpi/` and after any reboot reports `unexpected_shutdown: true` when the previous boot has no clean-shutdown marker — so "the Pi died" survives the power loss and shows as a persistent warning until acknowledged. This is how the dashboard can explain a dead device to the user after replugging.
- 2026-10-26 implementation progress: boot recorder prototyped in `systemd/travelpi-power-record.sh` (+ `systemd/travelpi-power-record.service`, oneshot start/stop). Verified on the live Pi in a sandbox: writes valid JSONL to `/var/lib/travelpi/power-log.jsonl` (`boot` events carry `throttled` + `core_volts`; `clean-shutdown` marker via the unit's stop hook), and emits `unexpected-shutdown` when the prior boot was not marked clean. Remaining: wire install + enable into the Makefile deploy target, expose `unexpected_shutdown` in the helper `power_status()`, and show it in the UI power chip.
- 2026-10-26: with both supplies restored, the Pi rebooted clean (`throttled=0x0`, core 1.2563 V) and the full DNS stack (AdGuard Home → Unbound) came back automatically under the Quadlet restart policy.
- 2026-10-26 **implemented, deployed, and verified live**:
  - Helper (`power_status`): canonical firmware bit map decoded (`0x1` uv-now, `0x2/0x4` capped/limited-now, `0x8` temp-now; history in both legacy `0x10–0x80` and modern `0x10000–0x80000` encodings — a Zero 2 W brown-out on current firmware reports `0x10000`). New keys: `signal` (priority order), six decoded flags, `raw_throttled`, `core_volts`, `current_ma`/`power_w`/`current_sensor` (INA219/INA226 hwmon, null without hardware), `usb_otg_present`/`usb_devices`, `unexpected_shutdown`.
  - Boot recorder `systemd/travelpi-power-record.{sh,service}`: JSONL telemetry at `/var/lib/travelpi/power-log.jsonl`, clean-shutdown marker via stop hook, `unexpected-shutdown` event detection; installed + enabled by `make deploy`.
  - UI: "Pi health" card power indicator — chip labels (`Power OK` / `Under-voltage NOW` / `Under-voltage history` / `Throttling` / `Thermal` / `No telemetry`), warning states, `Power loss shutdown` override when the recorder reports an unclean previous boot, detail line with core volts / current draw (or INA219-optional note) / OTG port + device count / raw flags.
  - Live payload on the Pi: `signal: clean`, `core_volts: 1.2563`, `usb_otg_present: true`, `usb_devices: 3`, `unexpected_shutdown: false`. All `make check` gates green, including new bit-decode, recorder, and UI fixtures.
  - Field note: single-supply operation killed the Pi twice during this session; `get_throttled` history resets to `0x0` on power loss, which is exactly why the persistent `unexpected_shutdown` marker exists.
