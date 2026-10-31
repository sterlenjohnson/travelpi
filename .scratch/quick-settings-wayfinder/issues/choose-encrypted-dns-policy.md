---
title: Choose optional encrypted-DNS policy
labels:
  - wayfinder:grilling
status: closed
parent: ../map.md
---

## Question

If encrypted upstream DNS is offered in Quick Settings, which fixed providers/endpoints and fallback policy are acceptable for hotel use?

The decision must cover bootstrap DNS, certificate/SNI handling, captive-portal detection, whether AdGuard or Unbound owns the encrypted transport, and the status labels shown when encrypted DNS is unavailable. The default recursive AdGuard → Unbound path remains unchanged until this decision is made.

## Resolution

Keep AdGuard Home → recursive Unbound as the default. Add an explicit optional DoH mode owned by AdGuard, initially using the fixed Cloudflare endpoint `https://cloudflare-dns.com/dns-query`.

Before enabling DoH, run the Pi-originated WAN probe. If it reports `CAPTIVE_PORTAL`, show **Hotel sign-in mode** and temporarily use the normal DNS path. Re-enable DoH only after the probe reports `INTERNET_OK`.

If DoH later fails, report `DNS_PRIVACY_DEGRADED` and require an explicit **Use normal hotel DNS** action. Never silently fall back and claim encrypted DNS is active.
