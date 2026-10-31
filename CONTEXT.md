# TravelPi Cockpit domain context

## Core terms

- **Hotel connection**: the `wlan0` association and network path used as the preferred Internet WAN.
- **Remembered hotel SSID**: a non-secret convenience hint that TravelPi may retain to simplify reconnect setup. It contains no password or hotel identity.
- **Hotel identity**: the temporary MAC choice used for the current hotel connection. TravelPi does not persist hotel MAC identities or hotel credential profiles.
- **WAN identity policy**: the choice between the hardware MAC, a temporary manual clone, or asking before applying a clone. The clone option remains available without hotel profile persistence.
- **Captive portal**: a reachable hotel network that redirects HTTP requests to a sign-in page. It is not treated as a radio or DHCP failure.
- **WAN probe**: a lightweight HTTP check originating on the Pi after association, DHCP, route setup, or identity change. It distinguishes Internet access from captive-portal access.
- **Verified WAN**: a hotel connection that has association, DHCP, a default route, and a successful WAN probe.
- **Readiness evidence**: fixed, read-only host facts used to decide whether a disruptive operation is supported before it is confirmed or applied.
- **Hotel scan**: a fixed `wlan0` scan that returns sanitized SSIDs and signal facts; it never returns credentials or automatically connects.
- **Radio role assignment**: choosing which detected WiFi radio is WAN (STA) and which are LAN (AP), configured as one WAN plus one-or-more LAN from a menu of radio hardware names. Only meaningful when two or more WiFi radios are present. The WAN (STA) radio retains its MAC identity under the WAN identity policy.

## Safety boundaries

- The Pi detects captive portals but does not automate arbitrary portal login.
- Passwords and hotel credential profiles are not newly persisted by TravelPi. Remembered SSIDs are permitted because they are non-secret; existing NetworkManager connection profiles remain authoritative until the transient-profile design is implemented.
- MAC changes and reconnects remain confirmed and staged/transactional.
- A failed identity change must attempt to restore the previous working identity.
- WAN probes are lightweight and are not speed tests.
- Wired-uplink and role-switch readiness remain unverified without a connected LAN uplink; no role flip is automatic.
- Wi-Fi 6E detection does not imply that 6 GHz or all-band AP configuration is tested or available.
- Radio role assignment is a real configuration concept but is not auto-applied: a safe role swap needs a verified LAN uplink, and no role flip is automatic. Until the backend supports a safe swap, the action surfaces an honest unavailable notice rather than staging a command the coordinator cannot execute.
