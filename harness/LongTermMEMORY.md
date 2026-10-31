# C3 Memory (Every call)

Durable facts about this repository and the TravelPi design. Re-check them against
the code after a large refactor; they are anchors, not instructions.

## Network roles

- `wlan0` is the hotel WAN (STA); `wlan1` is the LAN AP. Source of truth:
  `helper/travelpi-cockpit` and the README.
- AdGuard Home runs as a rootless Quadlet unit at
  `systemd/user/adguardhome.container` with a 192 MiB memory ceiling and host
  networking.
- Tailscale stays a native `tailscaled` service on purpose: it owns the host's
  default route and network namespace.
- PackageKit is masked by deployment; `systemd/packagekit/resource-guard.conf` is
  the resource guard that replaces its default behaviour.
- VPN units the helper manages: `tailscaled`, `wg-quick@wg0`, and
  `openvpn-client@travelpi.service`.

## Repository layout

- `travelpi.ts` is the DOM/event shell, `travelpi-projection.ts` is the canonical
  status projection, `travelpi-contracts.ts` holds mutation and status contracts.
- `travelpi.js` and `travelpi-typed.js` are generated browser artifacts that are
  committed and rebuilt by `make check`.
- `helper/travelpi-cockpit` is a Python 3 helper with no file extension; tests load
  it through `importlib.machinery.SourceFileLoader` in `tests/`.
- Host paths: package at `/usr/share/cockpit/travelpi/`, helper at
  `/usr/local/libexec/travelpi-cockpit`.
- Issues and specs live under `.scratch/<feature-slug>/` per
  `docs/agents/issue-tracker.md`; domain vocabulary in `CONTEXT.md`; decisions in
  `docs/adr/`.

## Design rules and traps

Host-specific measurements and incident history live in the untracked
`harness/LongTermMEMORY.local.md` when it exists; treat it as optional. The rules
below are the durable, host-independent part. Placeholders: `<pi-host>`,
`<tailnet>.ts.net`, `<home-router-ip>`.

- Power: the Pi Zero 2 W class of board can brown out under load on a single
  supply. `get_throttled` history is volatile; the power recorder at
  `/var/lib/travelpi/power-log.jsonl` plus the `unexpected_shutdown` flag is what
  survives a crash. USB `bMaxPower` values carry an `mA` suffix: parse digits.
- Quadlet: older quadlet versions drop units that use `PullPolicy`; do not use it.
  Do not mount `Volume=tmp:` (collides with a plain `tmp` podman volume); use the
  named tmpfs volume `travelpi-adguard-stats`. `podman volume create` exits 1 when
  the volume exists: deploy treats that as idempotent.
- When `/etc/containers/systemd/adguardhome.container` exists, the rootful system
  quadlet is canonical and deploy masks the rootless user quadlet.
- journald is `Storage=volatile`; AdGuard stats live on tmpfs.
- Timekeeping: the host has no RTC. Never use `time.time()` for TTLs at boot; use
  monotonic uptime. Never disable the live time service (`ntpsec` on Pi OS builds
  that ship it).
- Radio watchdog `travelpi-radio-watch.service` escalates carrier loss: link cycle,
  USB unbind/bind, hostapd restart. Do NOT add `BindsTo=hostapd`: the watchdog
  restarts hostapd and would stop itself.
- Memory watchdog `travelpi-mem-watch` stops optional services before killing the
  largest non-protected process; core network daemons carry negative
  `OOMScoreAdjust`, AdGuard positive. `sh -n` any watch loop; `A || B && C`
  is `(A||B)&&C` in sh.
- AdGuard stays the filtering layer: loading a full blocklist into Unbound uses
  more RAM, not less. Unbound is the small fallback resolver.
- AdGuard split DNS lives in `upstream_dns`. A leading dot in the pattern
  (`[/.domain/]`) is REJECTED by AdGuard v0.107 and crash-loops DNS: never
  generate it. Keep `nat64_prefix` at exactly 2-space indent (grep anchored
  `^  nat64_prefix:`); a 3-space duplicate breaks the yaml parse. The NM
  dispatcher `systemd/travelpi-adguard-hotel-dns` regenerates the block from DHCP
  nameservers and every tailnet MagicDNS domain on `dhcp4-change`; a tailnet can
  carry more than one domain. `/etc/travelpi-home-dns` ("domain ip" pairs) adds
  home names.
- Tailscale JSON: `"DNSName": "name.<tailnet>.ts.net."` has a space after the
  colon and a trailing dot; parse both. Use `Self.PrimaryRoutes` (`Self.Ads` is
  deprecated and empty). Helper `status` nests under `{"ok":..,"status":{..}}`.
- Subnet routing: home routers must advertise specific /24s, never a supernet
  covering the Pi's own local ranges (tailscaled then installs nothing). Routes may
  live in routing table 52, so check `ip route get`, not `table 89`. Advertised
  routes need tailnet admin approval. `tailscale ping <lan-ip>` finds the serving
  router even without a kernel route.
- Tailscale SSH (`tailscale set --ssh --accept-risk=lose-ssh`) needs one browser
  check by the node owner first; until then tailnet port 22 hangs.
- IPv6: networkd (`systemd/network/travelpi-ap.network.in`, rendered by
  `travelpi-ula-init` into `070-travelpi-ap.network`) sends RAs and OWNS the AP addresses via `Address=`
  (`192.168.200.1/24` and the `::1` of the per-install ULA /64 in
  `/etc/travelpi/ula-prefix`; never hardcode a ULA, ADR 0006 Update). The keeper heals link flaps and
  NEVER restarts networkd (a restart flushes its addresses; a restart on every
  tick shows as "AP addresses applied" every 15s). `ip addr flush` on the AP wipes
  the IPv6 link-local, which the kernel will not regenerate: flush IPv4-scoped and
  recover via `disable_ipv6` 1->0. radvd 2.20 privsep was broken on the reference
  host (no interface resolved); ADR 0006 chose networkd. `radvd.conf` stays as a
  rollback artifact: re-enabling radvd requires removing the networkd file. The
  `.network` Match is interface-name based (`wlan1`), so a role swap needs it
  regenerated. `sysctl` on Pi OS has no `-i`; use `-q -p file`.
- Radio driver: the MT7921/MT7925 USB ID `0e8d:7961` is bound to `mt7921u` by
  default; `mt7925u` claims only `0e8d:7925` on some kernels. The radio-driver
  script gates on `modinfo -F alias mt7925u` covering the device idProduct and
  removes the blacklist when unsupported (honest unavailable). Bind through
  interface-driver dirs: `drivers/usb/bind` takes the DEVICE dir. `iw` lives at
  `/usr/sbin/iw`. 6 GHz refuses with `radio_capability_missing` without host
  evidence.
- Config backup: `travelpi-config-backup` daily to `/var/lib/travelpi/backups`;
  rotation using `tail` needs `tail -n +N+1`. `make backup-pull`, `make restore`.
- Portal hint: `portal_status()` probes a plain-HTTP URL; a redirect to a private IP
  means portal. Display only, never automate login. TTL on monotonic uptime.
- Cockpit serving: `cockpit-ws` caches app bundles; deploy ends with
  `systemctl restart cockpit.service` (sessions drop). Unauthenticated
  `GET /travelpi/*` returns the login page, so verify deployed assets by grepping
  files on the host.
- Cockpit manifest nests the UI into five pages (index, hotel, vpn, network,
  health); one shared `travelpi.js` serves all, every page repeats the chrome, and
  `tests/manifest-pages.py` guards registration.
