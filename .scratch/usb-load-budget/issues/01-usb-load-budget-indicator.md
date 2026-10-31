---
title: USB load budget indicator on the shared 5V rail
labels:
  - ready-for-agent
status: closed
---

## Question

How should Cockpit show USB power demand so the dual-supply requirement is quantified, not guessed?

Facts (2026-10-26): Pi Zero 2 W merges the PWR and OTG micro-USB inputs onto one 5V rail; a single supply browns out and kills the Pi under current load (observed twice). The OTG port runs as DWC2 host with a hub + MT7921U Wi-Fi adapter (`usb_devices: 3` live). USB devices advertise current demand via `/sys/bus/usb/devices/*/bMaxCurrent` (mA; 0 = virtual).

Required outcome:

- Helper sums `bMaxCurrent` over connected device directories (reuse the `USB_DEVICE_RE` inventory from `power_status()`) → `usb_demand_ma`.
- Status payload + Quick Settings power detail line shows `USB load ~N mA` beside the existing core-voltage/OTG facts; rail budget context (500 mA host-advertised / dual-supply recommended) in the detail copy.
- Warning state when demand exceeds 500 mA with the supply count unknown, and against measured draw when an INA219 (see `.scratch/ina219-current-sense/`) is present.

Constraints: read-only sysfs, additive payload keys (`usb_demand_ma`), contract + view-model + frontend fixture updates, `make check` green.

## Comments

- 2026-10-26: Field evidence — single supply = brownout death; OTG feeds hub + Wi-Fi adapter through the same rail.
- Live notes: `usb_demand_ma: 300` on the Pi (hub 100 + MT7921U 100 + USB-LAN 100 via bMaxPower, mA-suffix parsing verified); UI detail "3 USB devices · ~300 mA demand" verified by fixture + live payload.
