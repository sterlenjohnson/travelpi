# ADR 0006: AP router advertisements come from systemd-networkd, not radvd

## Status

Accepted. 2026-10-30.

## Decision

- **RA layer: systemd-networkd.** The AP's router advertisements are
  produced by systemd-networkd from
  `systemd/network/travelpi-ap.network.in` (rendered into
  `/etc/systemd/network/070-travelpi-ap.network`): the install's ULA
  prefix from `/etc/travelpi/ula-prefix` with `Autonomous=true`, NAT64 route
  `64:ff9b::/96`, `AcceptRA=no`, intervals 30 s / 100 s. Deployment
  enables `systemd-networkd` (socket + service) and disables `radvd`.
- **radvd 2.20 is broken on the reference host (Pi OS, radvd 2.20).** With privsep, the sandboxed
  sender child resolves NO interface — `"wlan1" not found: No such
  device`, identical for `lo` — so `setup_iface=-1` and no RA ever left
  the radio while the unit sat active and the config test passed. The
  ULA SLAAC failure that ADR-adjacent incident work traced to the keeper's
  address flush had a second, independent cause behind it.
- **Addressing ownership: networkd owns the AP addresses.** The
  `.network` declares `Address=192.168.200.1/24 <ula-gateway>/64` (the `::1` of the install's ULA /64)
  so networkd configures them (replace semantics, idempotent) and the
  keeper acts as a heal-watchdog for link flaps. The keeper never
  restarts systemd-networkd: a networkd restart removes the addresses it
  owns, and when the keeper restarts it on every address-missing tick the
  AP oscillates — addresses vanish every 15 s, DHCP dies, and LAN clients
  lose internet (hit live 2026-10-30: networkd's first configure, before
  Address= existed, flushed the keeper's addresses, and the keeper's
  restart-on-v6-missing turned the recovery into a 15 s cycle). The
  helper's deliberate role-apply restart is fine: it is one reconfigure
  on a deliberate change, not a watchdog loop.

## Rationale

radvd's privsep sandbox is a compile-time property (no config switch),
and it fails on every interface on this kernel/systemd pair — a daemon
that advertises nothing while reporting "active" is exactly the
silent-failure class the guardrails forbid. systemd-networkd v257 ships
with the system, advertises prefixes, routes, and RDNSS with the same
RFC 4861 semantics, adds no new dependency, and its RA activity is
observable in the journal and on the wire (verified: 9 RAs in 45 s,
the ULA prefix with `Flags [onlink, auto]`).

## Consequences

- `tests/ap-address-guard.py` pins the `.network` contract (SendRA,
  AP `Address=`, prefix, autonomous, NAT64 route, AcceptRA=no), the
  keeper's ban on restarting systemd-networkd, and the deploy wiring
  (install 070-travelpi-ap.network, disable radvd, enable networkd).
- Deploy keeps installing `/etc/radvd.conf` (rollback artifact) and no
  longer apt-installs radvd, config-tests it, or re-enables it.
- `restore` re-enables `systemd-networkd` in place of `radvd`.
- A host that later runs a fixed radvd would need the unit re-enabled
  AND this `.network` removed to avoid duplicate advertisements.

## Update: per-install RFC 4193 prefix (2026-10-30)

The first deployment hardcoded the AP prefix inside `fd7a:115c:a1e0::/48`,
which is Tailscale's own ULA block, shared by every tailnet. That squatted
in a vendor's address space, gave every install of this project the same
non-unique prefix, and tied a vendor-neutral router to one VPN.

- **One source of truth:** `/etc/travelpi/ula-prefix`, one line holding a /64
  such as `fd12:3456:789a:1::/64` (override the path with
  `TRAVELPI_ULA_PREFIX_FILE`). The keeper, helper and networkd profile all
  read it; there is no hardcoded fallback. A host without the file has no
  ULA configured, and the helper reports that honestly (`ipv6.state` off,
  `set_ipv6 on` refused as `unavailable`).
- **Generator:** `systemd/travelpi-ula-init` (installed to
  `/usr/local/libexec/`) never overwrites an existing file and refuses a
  malformed one. If the file is absent it first **migrates** the prefix of
  an already-installed `070-travelpi-ap.network`, so a live router keeps
  its addressing and its clients keep their SLAAC addresses; otherwise it
  generates an RFC 4193 prefix (`fd` + 40 random bits, subnet id 1).
- **Template:** the tracked `.network` is now `travelpi-ap.network.in`
  with `@ULA_PREFIX@` / `@ULA_GATEWAY@`; `make deploy` runs
  `travelpi-ula-init`, then renders it (and the `radvd.conf` rollback
  template) before networkd is enabled or reloaded. All ADR 0006 rules stand:
  networkd owns the AP addresses, the keeper never restarts it, the NAT64
  route `64:ff9b::/96` is still advertised.
- **Tailscale stays optional.** Deploy advertises nothing over Tailscale
  unless the operator passes `ADVERTISE_ROUTES`, and then the list must
  include the operator's own ULA /64 for it to be routed.
- **Rotating** a prefix: edit the file, re-render (`make deploy`), and
  expect clients to renumber; a migrated install that wants to leave the
  Tailscale range can do exactly that.
