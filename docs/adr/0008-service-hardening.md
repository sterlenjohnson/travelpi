# ADR 0008: Conservative systemd hardening for TravelPi units

## Status

Accepted. 2026-10-31.

## Context

A security audit found that no TravelPi unit had any sandboxing, start limit
or memory ceiling, and all of them run as root on a 512 MB Pi. The router must
never be broken by hardening, so the rule is: add a directive only when the
script behind the unit provably does not need what it removes, and say so in a
`# hardening:` comment next to it. Directives are limited to systemd 252
(Debian 12/13). Distro-service drop-ins, `resource-guard.conf` and the AdGuard
quadlet are out of scope and unchanged.

## Decision

Baseline in `[Service]` for every TravelPi unit: `NoNewPrivileges=yes`,
`ProtectHome=yes`, `RestrictRealtime=yes`, `LockPersonality=yes`,
`PrivateTmp=yes` (no script exchanges files through /tmp: state lives in
`/run` and `/var/lib/travelpi`, and the helper reads those, not /tmp), and a
`MemoryMax=` (64M for loops, keeper and oneshots, which peak near 15 MB live;
128M for config-backup). Units with `Restart=` also get `StartLimitIntervalSec=300`
and `StartLimitBurst=5` in `[Unit]`; hang-prone oneshots get `TimeoutStartSec=`.

| Unit | Extras | Deliberately omitted, and why |
| --- | --- | --- |
| travelpi-clockset | `CapabilityBoundingSet=CAP_SYS_TIME`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`, `ProtectSystem=strict`, `PrivateDevices=yes`, `ProtectKernelModules=yes`, `ProtectControlGroups=yes`, `TimeoutStartSec=30` | `ProtectClock` (blocks `date -u -s`). `AF_UNIX` kept beyond the requested two families for libc/NSS name-service sockets; curl itself is the only network user. |
| travelpi-config-backup | `ProtectSystem=full`, `TimeoutStartSec=300`, `MemoryMax=128M` | `strict`: needs a ReadWritePaths list tied to the script's test seam; it reads /etc, /opt, /var/lib/tailscale and writes only /var/lib/travelpi. |
| travelpi-mem-watch | `ProtectSystem=full` | `ProtectProc`/`PrivateUsers`/`CapabilityBoundingSet` (needs CAP_KILL and a view of all processes), `RestrictAddressFamilies` and `PrivateNetwork` (systemctl uses AF_UNIX). |
| travelpi-power-profile | `ProtectSystem=strict` + `ReadWritePaths=/sys/devices/system/cpu`, `PrivateNetwork=yes`, `TimeoutStartSec=30` | `CapabilityBoundingSet` (left out: unverified on the Pi whether sysfs writes need an override capability). |
| travelpi-power-record | `ProtectSystem=full`, `TimeoutStartSec=30`, `TimeoutStopSec=30` | `PrivateDevices` (vcgencmd opens /dev/vcio). |
| travelpi-radio-driver | `TimeoutStartSec=180` | `ProtectSystem` (removes /etc/modprobe.d blacklist), `ProtectKernelModules` (modprobe), `ProtectKernelTunables` and `PrivateDevices` (writes /sys USB bind), `PrivateNetwork`/address-family limits (systemctl). |
| travelpi-radio-watch | `ProtectSystem=full` | `ProtectKernelTunables`/`PrivateDevices` (USB unbind/bind in /sys), `RestrictAddressFamilies` (ip netlink, systemctl AF_UNIX). No `BindsTo=hostapd` (it restarts hostapd). |
| travelpi-sqm-tune | `TimeoutStartSec=180` | `ProtectSystem` (rewrites /etc/default/travelpi-sqm), `PrivateNetwork`/address-family limits (`curl --interface wlan0`). |
| travelpi-sqm | `ProtectSystem=full`, `TimeoutStartSec=60`, `TimeoutStopSec=60` | `ProtectKernelModules` (modprobe sch_cake/ifb), address-family limits (tc/ip AF_NETLINK). |
| wlan1-static-ip | `ProtectSystem=full` | `ProtectKernelTunables` (writes /proc/sys for the link-local toggle), address-family limits (AF_NETLINK, AF_UNIX for nmcli and systemctl). |

`ProtectSystem=strict` is only allowed where every write is under an explicit
`ReadWritePaths` (`/sys` and `/dev` are outside strict's read-only set anyway).
`PrivateNetwork=yes` is only allowed for power-profile. `tests/unit-hardening.py`
encodes the table, including which scripts write outside `/run` and
`/var/lib` and which need the network.

### Ordering: no PartOf=hostapd for the AP keeper

`wlan1-static-ip.service` does not get `PartOf=hostapd.service`. The keeper
re-reads `hostapd.conf` every tick and heals address loss itself (ADR 0006).
With PartOf, stopping hostapd (radio-driver switch, memory guard) would stop
the healer too, and every radio-watch hostapd restart would restart the keeper
and count against its start limit.

## Consequences

- A crash loop in a `Restart=always` unit (mem-watch, radio-watch, keeper)
  stops after five starts in five minutes and the unit stays failed until
  `systemctl reset-failed` / restart; the dashboard heartbeat shows the
  watchdog as stale. This is the accepted trade for not spinning on a 512 MB Pi.
- A script that grows past `MemoryMax` is killed by the cgroup, not the host.
- Anyone adding a TravelPi unit must add it to the table in
  `tests/unit-hardening.py`, which fails on an unlisted unit.

## Verification on a Pi

```sh
systemd-analyze verify /etc/systemd/system/travelpi-*.service /etc/systemd/system/wlan1-static-ip.service
systemd-analyze security travelpi-clockset.service travelpi-power-profile.service wlan1-static-ip.service
systemctl show -p MemoryMax,NoNewPrivileges,ProtectSystem <unit>
```

After `make deploy`, confirm the AP still has its addresses, `radio-watch` and
`mem-watch` heartbeats advance, and `sudo systemctl start travelpi-clockset`
exits 0.
