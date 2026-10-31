---
title: Specify DoH transition and verification
labels:
  - wayfinder:research
status: closed
assignee: pi
parent: ../map.md
---

## Question

What exact allowlisted AdGuard configuration changes and helper health checks implement the accepted optional Cloudflare DoH mode?

The answer must cover: the fixed endpoint representation, bootstrap resolution, certificate/SNI verification, captive-portal gating, atomic config update, rollback to AdGuard → Unbound recursive mode, and the status evidence needed for `DNS_PRIVACY_DEGRADED`. It must fit the existing root-owned helper boundary and avoid accepting arbitrary endpoints from the GUI.

## Resolution

Official AdGuard Home documentation supports `https://.../dns-query` upstreams, `bootstrap_dns`, and upstream testing. Its OpenAPI defines `GET /control/dns_info`, `POST /control/dns_config`, and `POST /control/test_upstream_dns`. The implementation should use a fixed allowlisted Cloudflare DoH value, test it before switching, preserve the recursive configuration for rollback, and report configured/tested state separately from the WAN probe. Captive-portal mode remains explicit and must not silently claim DoH after falling back.

Research notes: [`docs/research/doh-transition-and-verification.md`](../../../docs/research/doh-transition-and-verification.md).
