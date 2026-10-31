---
title: TravelPi Quick Settings and Privacy Stack
labels:
  - wayfinder:map
status: open
---

## Destination

A build-ready specification for a lightweight TravelPi Quick Settings surface covering the existing AdGuard Home → Unbound DNS stack, optional encrypted DNS, IPv6 readiness, SQM, and WAN identity status without persisting hotel MAC profiles or duplicating AdGuard's full GUI.

## Notes

- Repository: `travelpi-cockpit`.
- Use `CONTEXT.md`, ADR 0001, `travelpi-cockpit` skill, grilling, and domain-modeling.
- Preserve the Pi Zero 2 W budget, Cockpit authentication, staged disruptive changes, and the `the activation script` activation path.
- This is a planning map. Resolve one decision ticket at a time; do not implement the destination while open tickets remain.

## Decisions so far

- [No persistent MAC profiles](issues/no-persistent-mac-profiles.md): hotel identity is temporary; retain a visible/copyable current MAC and manual clone option.
- [Normalize AdGuard runtime for stealth mode](issues/normalize-adguard-runtime.md): dnsmasq becomes DHCP-only so host-networked AdGuard can own LAN DNS port 53; the stealth script remains the activation authority.
- [Default recursive DNS path](issues/default-recursive-dns.md): preserve AdGuard Home → Unbound as the default; DoH/DoT is optional and must not be mislabeled.
- [Choose optional encrypted-DNS policy](issues/choose-encrypted-dns-policy.md): optional AdGuard-owned Cloudflare DoH, with explicit hotel sign-in mode and no silent fallback.
- [Specify DoH transition and verification](issues/specify-doh-transition-and-verification.md): use AdGuard's fixed upstream/test configuration with bootstrap DNS, preserve recursive rollback, and report DoH verification separately from WAN reachability.
- [IPv6 safety posture](issues/ipv6-safety-posture.md): detect upstream IPv6 first; report unavailable/available/LAN-only and do not advertise fake Internet IPv6.
- [Quick Settings safety model](issues/quick-settings-safety-model.md): stage DNS, IPv6, SQM, and identity changes; confirm service restarts; keep AdGuard's full administration in its own GUI.

## Not yet specified

- The exact runtime implementation change needed to make dnsmasq DHCP-only and make the stealth script verify AdGuard startup.
- The eventual implementation and helper API surface for the accepted DoH and AdGuard runtime decisions.
- The IPv6 delegation, RA/DHCPv6, firewall, and client behavior once an upstream prefix is available.
- The compact layout and status vocabulary for Quick Settings on desktop and mobile.

## Out of scope

- Replacing AdGuard Home's administration UI.
- Automatic captive-portal authentication.
- Persistent hotel MAC profile storage.
- Transactional WAN-radio switching or second-radio failover implementation.
- Speed tests, Wi-Fi scans, and live graphs.

## Open children

- [Define IPv6 delegation and firewall policy](issues/define-ipv6-policy.md) — unblocked.
- [Prototype the Quick Settings surface](issues/prototype-quick-settings-surface.md) — blocked by Define IPv6 delegation and firewall policy.
- The dnsmasq/stealth-script runtime implementation is now a later build task, after the remaining decisions are settled.
