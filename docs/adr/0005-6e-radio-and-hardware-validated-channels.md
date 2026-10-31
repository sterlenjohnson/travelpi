# ADR 0005: The 6E radio binds to mt7925u; AP channels are hardware-validated

## Status

Accepted. 2026-10-30.

## Decision

- **Driver binding, gated on kernel support.** The USB AP radio reports
  the shared ID `0e8d:7961`, claimed by `mt7921u` (2.4/5 GHz) in kernel
  6.12.75+rpt; `mt7925u` in that kernel claims `0e8d:7925` only (the
  MT7925AU reuse of `7961` arrives in newer kernels — OpenWrt's newer
  mt76 sees the 6E band). Deployment installs
  `/etc/modprobe.d/travelpi-mt7925.conf` blacklisting `mt7921u`/
  `mt7921_common` and runs the live switch `travelpi-radio-driver`, but
  the switch first verifies the target's module alias table covers the
  device's actual product ID. When it does not (some kernels today, e.g. 6.12.75), the
  switch removes the blacklist, keeps `mt7921u`, and reports the honest
  unavailable reason — an unbound radio must never be the outcome.
  Binding goes through the interface-driver directories
  (`drivers/mt7925u/bind` with the interface dir); `drivers/usb/bind`
  takes the device dir and silently failed in the first version.
- **Channel validation comes from the hardware.** `set_ap_radio` accepts an
  optional channel, and the helper validates it against the channels
  `iw phy info` reports for the requested band, excluding radar (DFS)
  channels. With no channel requested, the canonical channels stay
  (2.4 → 6, 5 GHz → 36). A channel pick with no `iw` read is refused with
  the honest unavailable notice, never guessed.
- **6 GHz is offered only on host evidence.** The UI shows the 6 GHz band
  only when the AP radio's reported `supported_channels` include 6 GHz;
  the helper refuses `band: 6ghz` with `radio_capability_missing` when the
  radio has not reported the band. The 6 GHz hostapd profile
  (`ieee80211ax=1`, `he_6ghz=1`) is written only after that gate passes.

## Rationale

The shared USB ID makes driver choice a race resolved by a blacklist file
— a deploy-time, visible, reversible fact, not a modprobe guess. Channel
and band claims in the UI must trace to the radio's own report (the
pi-host-evidence rule): an unattended travel AP must not pick a DFS
channel, and 6 GHz parameters must not reach hostapd on a radio that has
not proven the band.

## Consequences

- `tests/radio-driver-switch.py` pins the blacklist contents, the
  bind/verify/restore sequence in the switch script, its deploy wiring,
  and the helper's journal matcher counting `mt7925` flap events.
- The gate also runs at every boot as `travelpi-radio-driver.service`
  (oneshot, `After=systemd-modules-load.service`, `Before=hostapd.service`),
  because a kernel change can leave the blacklist in place with no driver
  claiming the stick. A driverless radio (no netdev, or a phy with no bound
  driver) is repaired: `mt7925u` is bound when its alias table covers the
  USB product id, otherwise the blacklist is removed and `mt7921u` is
  rebound. At boot the script never calls `systemctl` (hostapd has not
  started yet). `tests/radio-driver-switch.py` runs the real script against a
  fake sysfs with command shims to assert this behavior.
- "(no IR)" channels are excluded from the AP-usable `supported_channels`
  (an AP may not initiate radiation there) but still count toward the WAN
  client's band report.
- `tests/radio-capabilities.py` pins the channel parsing with DFS
  exclusion; `tests/helper-command-paths.py` pins channel validation,
  the 6 GHz evidence gate, and that refusals touch neither hostapd.conf
  nor the host.
- The switch bounces the AP briefly at deploy; the address keeper
  (`travelpi-ap-ip`, see the ULA fix) re-applies the AP's v4 and v6
  addresses within its 15 s window after hostapd recreates the interface.
