# ADR 0001: Hotel profiles and Pi-originated WAN probes

## Status

Accepted for WAN probes; hotel profile persistence superseded by the no-persistent-MAC decision.

## Decision

Do not store hotel profiles or hotel MAC identities. Keep the current WAN identity visible and copyable, and keep manual MAC cloning available as an explicit confirmed action. Existing NetworkManager profiles remain authoritative.

After association, DHCP, route setup, or an identity change, run a lightweight HTTP probe from the Pi. Report captive portal separately from no DHCP, no route, and no Internet. Do not automate arbitrary captive-portal authentication.

## Rationale

Hotel networks often require a stable device identity, but not every hotel requires cloning. A Pi-originated probe gives a reliable signal for whether association and identity changes actually produced Internet access without treating captive portals as radio failures.

## Consequences

The helper remains authoritative for connection state and probe results. Identity changes need rollback because they can interrupt the WAN. Credentials stay governed by NetworkManager and are not copied into TravelPi storage.
