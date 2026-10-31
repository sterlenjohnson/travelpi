# ADR 0007: Global IPv6 for AP clients via DHCPv6 prefix delegation

## Status

Accepted, partially implemented. 2026-10-31.

## Decision

- DHCPv6 prefix delegation (PD) from the upstream network is the supported
  route to a real global IPv6 address for AP clients. The Pi would receive a
  prefix on the WAN radio and route a /64 of it to the AP.
- This ADR implements only the probe: the read-only, root-only `pd` helper
  command (`dhcpv6_pd_probe`) sends a single SOLICIT with an IA_PD option on
  the WAN interface and parses the ADVERTISE/REPLY. It never sends a
  REQUEST, so no lease is taken. It listens on a raw UDP socket so it does
  not contend with NetworkManager for UDP 546. The UI shows the result and
  states plainly that AP delegation is not implemented.
- The PD client is a follow-up. Which component requests and renews the
  prefix is undecided, because NetworkManager owns the WAN radio; the
  choice must not fight NetworkManager for UDP 546 or restart networkd
  (ADR 0006).

## Alternatives considered

- NDP proxying: fragile, needs per-address handling and upstream cooperation.
- NAT66: breaks end-to-end addressing and is non-standard.

## Consequences

- Users learn whether their router offers PD before any automation exists.
- Hotel networks will almost always report `not_offered`; ULA stays the
  honest state there.
- Nothing is staged or claimed as working for delegation until the client
  lands. Until then the helper's `ipv6.state` is never `active`: it reports
  only `ula-only` (networkd running with the installed AP profile and no
  `ra-off` drop-in) or `off`, plus the observed facts `wan_global` and
  `ap_global`. A future ADR records the client component and AP re-addressing.
