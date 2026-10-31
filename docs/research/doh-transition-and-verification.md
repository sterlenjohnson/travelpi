# DoH transition and verification research

## Scope

Research for the Wayfinder ticket **Specify DoH transition and verification**. Sources are official AdGuard Home and curl documentation.

## Findings

### AdGuard Home accepts fixed DoH upstreams

AdGuard Home's configuration documentation lists `https://dns-unfiltered.adguard.com/dns-query` as an encrypted DNS-over-HTTPS upstream format. The same section distinguishes `h3://.../dns-query` as forced HTTP/3, so ordinary `https://` is the safer first mode because it permits the normal HTTPS transport fallback.

Source: [AdGuard Home configuration](https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration)

### Bootstrap DNS is a first-class setting

AdGuard Home defines `bootstrap_dns` as the DNS servers used for initial hostname resolution when an upstream server name is a hostname. Its configuration also defines `upstream_dns`, `fallback_dns`, and `bootstrap_prefer_ipv6`.

Source: [AdGuard Home configuration](https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration)

### The supported API has read, update, and test operations

The official OpenAPI document defines:

- `GET /control/dns_info` (`dnsInfo`)
- `POST /control/dns_config` (`dnsConfig`)
- `POST /control/test_upstream_dns` (`testUpstreamDNS`)

The DNS configuration schema includes `bootstrap_dns` and `upstream_dns`. The upstream-test endpoint accepts an `UpstreamsConfig` request and reports per-server test status.

Source: [AdGuard Home OpenAPI specification](https://github.com/AdguardTeam/AdGuardHome/blob/master/openapi/openapi.yaml)

### Plain DNS is a separate serving setting

AdGuard Home documents `serve_plain_dns` as controlling plain DNS serving. It cannot be set to false unless one or more encrypted protocols are enabled. This means the product may continue serving LAN DNS on port 53 while using DoH for its upstream path; disabling client-facing plain DNS is a separate design choice and should not be conflated with encrypted upstream DNS.

Source: [AdGuard Home configuration](https://github.com/AdguardTeam/AdGuardHome/wiki/Configuration)

### curl can bind a probe to an interface, but DNS binding is separate

The curl manual defines `--interface` as performing the operation using a specified interface. It separately documents `--dns-interface` for sending outgoing DNS requests through a specified interface, when the curl build supports c-ares. Therefore a fixed verification request should use an interface-bound URL request and should not claim that hostname resolution itself was interface-bound unless that separate capability is verified.

The manual also defines `--connect-timeout` as limiting connection establishment and `--max-time` as limiting the whole transfer, which provides a bounded verification window.

Source: [curl command-line manual](https://curl.se/docs/manpage.html)

## Decision implications

1. Keep the current `AdGuard Home → Unbound recursive` path as the default.
2. Represent DoH as one fixed, allowlisted upstream string; do not accept an endpoint from the browser.
3. Use AdGuard's own configuration/test API if credentials and API availability are deliberately provisioned; otherwise use a root-owned helper with an allowlisted configuration template and atomic replacement.
4. Test the fixed upstream before switching. Preserve a backup of the known-good recursive configuration and restore it if the test or post-change WAN probe fails.
5. Verify both DNS privacy configuration and WAN reachability. A successful HTTP probe alone proves Internet access, not that AdGuard used DoH; the helper should report configured/tested state separately.
6. Keep captive-portal mode explicit. Do not silently fall back from a selected DoH mode and report it as active.
