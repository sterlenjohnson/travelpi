---
title: INA219 5V-rail current sensing — wiring plus already-built display
labels:
  - ready-for-human
status: ready-for-human
---

## Question

Wire an INA219 (I2C, address 0x44) across the Pi Zero 2 W 5V input so true current draw appears in Cockpit.

Facts (2026-10-26): the Zero 2 W has no onboard current sensor (`vsense`/`measure_volts 5V` unsupported, no `/sys/class/power_supply`). The cockpit already detects and displays an INA219/INA226 hwmon automatically: `current_sensor`/`current_ma`/`power_w` populate the power detail line the moment `/sys/class/hwmon/*/name` reports `ina219`. Nothing to build in software except I2C enablement.

Human steps:

1. Hardware: INA219 breakout (addresses 0x44–0x46) across 5V input feeding the PWR+OTG merged rail (the 0.1Ω shunt path), GND to Pi GND, SDA (GPIO2)/SCL (GPIO3) 3.3V-tolerant line.
2. Pi config: `dtparam=i2c_arm=on` in `/boot/firmware/config.txt`, `i2c-dev` available, kernel module `iio`/`ina219` hwmon driver (check `modprobe ina219`, add to modules-load) so it appears as hwmon.
3. Verify: `cat /sys/class/hwmon/hwmon*/name` shows `ina219`; cockpit power line flips from "no current sensor (INA219 optional)" to live mA/W.
4. Record measured brownout threshold (single supply vs dual) in this ticket — that number is the point of the exercise.

Software is done and tested (tests/power-telemetry.py sandbox fixtures); this ticket closes when hardware is wired and the live payload shows `current_ma: <number>`.

## Comments

- 2026-10-26: Display path verified in code and deployed; awaiting hardware.
- Live notes: software side complete — `systemd/modules-load/travelpi-ina219.conf` deployed (i2c-dev, i2c-bcm2835, ina2xx; kernel 6.12.75+rpt-rpi-v8 verified). Remaining human steps: `dtparam=i2c_arm=on` in /boot/firmware/config.txt, `echo ina219 0x44 > /sys/bus/i2c/devices/i2c-1/new_device`, then record the brownout threshold measured single- vs dual-supply.
