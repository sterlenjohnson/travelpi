# TravelPi reference

The full reference: features by page, what `make deploy` changes on the host, defaults and customizing, the helper protocol and action table, and the threat model. The short version is in the [README](../README.md).

TravelPi Cockpit turns a Raspberry Pi with two Wi-Fi radios into a travel router that you manage from the Cockpit web console you already have: one radio joins the hotel Wi-Fi, the other runs your private access point. It is a small static Cockpit package plus one narrow, root-owned helper, so there is no extra login page, no framework, no bundler and no remote asset, and it is sized for a 512 MB Pi.

It exists because hotel networks are awkward (captive portals, MAC-bound sessions, flaky DNS) and a Pi on a marginal USB power supply fails in ways that are hard to see. TravelPi shows the real state of the uplink, the AP and the Pi itself, and offers a deliberately small set of confirmed actions instead of a general router editor.

## What it does

The package adds a "TravelPi" group to the Cockpit menu with five pages, named as in `manifest.json`: Router overview, Hotel & privacy, Tunnels & devices, Network & shaping, and Health & power. (The manifest lists the overview twice, as `index.html` and `travelpi.html`, only because the two files must stay identical; `tests/manifest-pages.py` guards that. It is one page in the UI.)

**Router overview**
- Preferred uplink (WAN) and private access point status at a glance, with a vitals strip and an issue banner.
- A WAN probe that tells apart association failure, no DHCP, no route, no DNS, captive portal and working Internet.

**Hotel & privacy**
- Wi-Fi scan and connect. Secured networks are detected from the scan and a blank password is flagged; the password is sent over stdin, never shown, and never stored by TravelPi. NetworkManager keeps whatever profile it normally keeps, and that profile stays authoritative. Failures are reported with a specific reason.
- WAN MAC: clone a MAC you supply, randomize, or reset to the hardware address. A failed change restores the previous setting.
- Captive-portal detection (display only: it probes a plain-HTTP site and reports a redirect). TravelPi never logs in to a portal for you.
- Per-radio band dropdowns. WAN: auto, 2.4 GHz or 5 GHz; 6 GHz is refused with an honest reason because NetworkManager has no 6 GHz selector. LAN: the AP radio profile (2.4 / 5 / 6 GHz where the radio reports support).
- AP identity (SSID and WPA2-PSK passphrase), AP profile and an optional channel validated against the channels the radio reports (radar/DFS channels excluded).

**Tunnels & devices**
- Tailscale, WireGuard (`wg-quick@wg0`) and OpenVPN (`openvpn-client@travelpi`) status, all optional. Tailscale and WireGuard can be toggled; Tailscale can be authenticated with an auth key or a sign-in link; OpenVPN is shown read-only. Wake-on-LAN for tailnet peers.

**Network & shaping**
- DNS stack: AdGuard Home (a Podman Quadlet container) with Unbound as fallback, or plain recursive Unbound. An optional tailnet-split mode forwards your tailnet domains to Tailscale DNS. The state is reported as `degraded` when AdGuard runs but real lookups fail (for example, upstream unreachable).
- IPv6: a per-install random ULA /64 stored in `/etc/travelpi/ula-prefix`, advertised to AP clients by systemd-networkd router advertisements. The helper reports the IPv6 state as `ula-only` or `off` (never a delegated-global state, ADR 0007), still reports `wan_global`/`ap_global` facts, and counts router advertisements as live only when systemd-networkd is active and the installed AP network file exists.
- CAKE/SQM traffic shaping with a manual rate, auto, or off; an opt-in timer re-tunes the rate.

**Health & power**
- Temperature, load, memory, swap and throttle flags; CPU governor; a button to drop page caches.
- Power recorder: undervoltage history and an "unexpected shutdown" flag that survive a crash (the kernel's `get_throttled` history does not).
- Radio watchdog (on repeated carrier loss: link cycle, then USB rebind, then hostapd restart; the USB stage is not yet confirmed to work on the validated host) and memory watchdog (stops optional services, then the largest non-protected process, within a kill budget), with their events shown in the UI.
- Daily configuration backup on the Pi, with `make backup-pull` and `make restore` to move it off and back.

## What it does not do

- **No role swap.** Choosing an arbitrary radio as WAN is modelled but refused unless readiness evidence passes (ADR 0002, 0004). The one-click "repair" only restores the tested layout (AP on the 5 GHz USB radio, WAN on the internal radio).
- **No global IPv6 for AP clients without a delegated prefix.** Clients get ULA addresses. Delegated-prefix handling is not implemented.
- **No per-client controls** (no blocking, shaping or pinning of individual devices).
- **No VPN kill switch.**
- **No captive-portal automation and no credential or hotel-MAC storage.**
- It is not a general NetworkManager, firewall or hostapd editor.

## Design principles

- **Static package.** Plain HTML, JavaScript and CSS served by Cockpit. TypeScript is a build-time tool only and is never run on the Pi. The only build is `npm`/`tsc` via `make test` (and so `make check`). A CSP in `manifest.json` allows same-origin scripts and styles only.
- **Staged, then confirmed, then applied.** Every change is shown first, confirmed in the browser, and enforced again in the helper (`confirm: true`). The helper accepts a fixed action vocabulary with strict fields, never a command, unit name or path from the browser.
- **Honest unavailable.** If the host has not demonstrated a capability, the UI says so instead of staging a command that cannot run, and an action that fails or is refused is never reported as applied.
- **No stored hotel secrets.** TravelPi does not persist hotel passwords or hotel MAC identities. Remembered SSIDs are the only convenience hint.
- **No portal login automation.**
- **512 MB budget.** Service memory ceilings, a volatile journal and bounded watchdogs.
- **Tailscale and every VPN are optional.** Nothing is advertised or enabled unless you opt in.

## How it compares

These are different tools with different scopes; this is a factual orientation, not a ranking.

- **RaspAP** is a standalone PHP web application for turning a Pi into a wireless router. TravelPi instead runs inside Cockpit with no separate web server of its own.
- **Travelmate** is an OpenWrt package that manages uplinks and can run auto-login scripts for captive portals. TravelPi runs on Raspberry Pi OS (Debian), shows portal state only, and does not log in for you.
- **GL.iNet** travel routers run commercial firmware on dedicated hardware. TravelPi is open source software for a Pi you already own and is validated on one hardware setup (see Status).

## Requirements

- Raspberry Pi OS (Debian) on a Raspberry Pi (only Debian 13 on a Pi Zero 2 W has been tested; see Status), with these installed and managed as usual: Cockpit, NetworkManager, hostapd, dnsmasq and systemd-networkd. Optional: AdGuard Home via Podman Quadlet, Unbound, Tailscale, WireGuard, OpenVPN.
- Two Wi-Fi radios. By default `wlan0` is the WAN (station, hotel Wi-Fi) and `wlan1` is the LAN access point at `192.168.200.1/24`. See "Defaults and customizing" to change this.
- On your computer: `make`, git, Node.js/npm, Python 3, and SSH access to the Pi with passwordless sudo. The lockfile pins `typescript` 7.0.2, whose `engines` field says Node >= 16.20.0 (it was developed on Node 24 and Python 3.14; there is no stricter pin in the repo, so use a currently supported Node LTS and a Python 3 that is not end-of-life).

### Prerequisites on the Pi

`make deploy` installs TravelPi's own files only. Before the first deploy, check that the Pi has:

- [ ] Cockpit (`cockpit-ws`, `cockpit-bridge`) and NetworkManager
- [ ] `hostapd`, `dnsmasq`, `unbound`
- [ ] `ntpsec` (deploy enables and restarts `ntpsec.service`)
- [ ] `systemd-networkd` (deploy enables it; it sends the AP's router advertisements)
- [ ] `podman` >= 4.4 with Quadlet support (the AdGuard unit is a `.container` file; the key set avoids `PullPolicy`, which older Quadlet rejects)
- [ ] `/opt/adguardhome/conf` and `/opt/adguardhome/work` directories (bind-mounted into the AdGuard container)
- [ ] `sudo` without a password for the SSH user, and `visudo`
- [ ] Optional: `tailscale` (only needed for the VPN card, `TAILSCALE_SSH`, `ADVERTISE_ROUTES`)

## Install

```sh
npm ci
make test
make deploy PI_HOST=<pi address> PI_USER=<user> PI_KEY=<path to ssh key>
```

`make test` builds the generated browser scripts, typechecks, compiles the helper and runs every product test; run it before anything else (`make deploy` and `make package` run it too). `make check` is the full maintainer gate: it also syncs and validates the agent harness (`make harness-check`) and then runs `make test`.

**Warning: `make deploy` changes the host.** It copies the package and helper to the Pi over SSH and, with sudo, installs systemd units, sysctl, modprobe and NetworkManager files, enables services (including systemd-networkd), masks PackageKit, applies memory and CPU guards, installs a sudoers entry for reading the AdGuard config, restarts NetworkManager, and finally restarts Cockpit, which can drop your session and briefly interrupt the Pi's own network. Read the `deploy` target in the `Makefile` before running it, run it from a console or a second route into the Pi, and try it on a spare SD card first.

Deploy variables: `PI_HOST` (default `travelpi.local`), `PI_USER` (`pi`), `PI_KEY` (`$HOME/.ssh/id_ed25519`). `PI_USER` must match `^[a-z_][a-z0-9_-]*$` (it is written into a sudoers line); `make deploy` and `make restore` stop early otherwise. Opt-ins: `RADIO_SWITCH=1`, `SQM_AUTOTUNE=1`, `TAILSCALE_SSH=1`, `ADVERTISE_ROUTES=<cidrs>`, `DISABLE_UNUSED_SERVICES=1`; opt-out: `SKIP_NM_RESTART=1` (details below).

`make package` builds the archive from an allowlist (`make package-list`: the pages, scripts, `cockpit/`, `helper/` and `systemd/` that deploy installs), so local backups, `node_modules`, tool logs and notes are never shipped. The archive is streamed to the Pi over SSH into a private `mktemp -d` directory that is removed when the remote command ends, including on failure.

### What make deploy changes on the host

| Change | Why | How to undo or skip |
| --- | --- | --- |
| Cockpit package to `/usr/share/cockpit/travelpi/`, helper to `/usr/local/libexec/travelpi-cockpit`, units and scripts under `/usr/local/{libexec,sbin,share/travelpi}` and `/etc/systemd/system` | The product itself | Remove the files and `systemctl daemon-reload` |
| `/etc/sudoers.d/travelpi-adguard` (written to a temp file, checked with `visudo -cf`, installed only if valid) | Lets the SSH user read the AdGuard config | Delete the file; skipped with a warning if validation fails |
| PackageKit masked (`mask --now`) plus a resource guard | Cockpit update polling exhausted zram | `sudo systemctl unmask packagekit.service` |
| journald set volatile (`10-travelpi-volatile.conf`) and restarted | Protects the SD card | Delete the drop-in, restart `systemd-journald` (logs are lost on reboot until then) |
| `/etc/sysctl.d/90-travelpi-ipv6.conf` applied | IPv6 forwarding and RA settings for the AP | Delete the file and reboot or reset the sysctls |
| `/etc/modprobe.d/travelpi-mt7925.conf`, `travelpi-radio-driver.service` enabled (the driver script itself runs live only with `RADIO_SWITCH=1`) (oneshot at boot, before hostapd) | Binds the right Wi-Fi driver for the AP radio (at boot the unit removes the blacklist and rebinds a driver if none is bound); removes the blacklist when the kernel lacks `mt7925u` | Delete the modprobe file; re-run or edit the driver binding |
| `/etc/NetworkManager/system-connections/travelpi-wired-wan.nmconnection` (eth0 DHCP, route metric 400 vs Wi-Fi 600, `autoconnect-priority=-10` so an existing static eth0 management profile keeps priority) | Prefer wired uplink when present | `nmcli connection delete travelpi-wired-wan` |
| NM dispatcher `95-travelpi-adguard-hotel-dns`, run once with the current resolvers | Keeps AdGuard upstreams in step with the hotel DNS | Delete the dispatcher file |
| Sandboxing in the TravelPi unit files (`NoNewPrivileges`, `ProtectHome`, `PrivateTmp`, `MemoryMax`, start limits, stricter profiles for clockset and power-profile; ADR 0008) | Limits the blast radius of root helpers on a 512 MB Pi | Remove the directives from the unit in `/etc/systemd/system` and `daemon-reload`; check with `systemd-analyze security <unit>` |
| `OOMScoreAdjust` drop-ins (core services -900, adguardhome +900), resource-guard drop-ins and `machine.slice`/`user.slice` caps | Under memory pressure the kernel sacrifices AdGuard, not the network | Delete the `*.service.d/travelpi-*.conf` and slice drop-ins, `daemon-reload` |
| Rootful AdGuard quadlet `/etc/containers/systemd/adguardhome.container`, tmpfs volume `travelpi-adguard-stats`, rootless unit masked; `adguardhome.service` restarted (brief DNS gap) | Canonical AdGuard on this Pi | Remove the quadlet, `systemctl --user unmask adguardhome.service` |
| `systemd-networkd` enabled; `/etc/systemd/network/070-travelpi-ap.network` rendered from your ULA prefix; `wlan1` reconfigured | networkd owns the AP addresses and sends RAs | Delete the file, `networkctl reload` |
| `/etc/radvd.conf` rendered, `radvd` disabled | Rollback artifact only; networkd sends the RAs | Delete the file |
| Timers and services enabled: config backup (**runs immediately**), power record, mem watch, power profile, radio watch, SQM, clockset | Resilience features | `systemctl disable --now <unit>` |
| `ntpsec.service` enabled and restarted | It is the live timekeeper here | None needed |
| `sudo systemctl restart NetworkManager` at the end | Picks up the wired profile | `SKIP_NM_RESTART=1` (reloads profiles instead) |
| `sudo systemctl restart cockpit.service` at the end | Flushes Cockpit's cached app bundle; your session drops | Log in again |
| Opt-ins: SQM auto-tune timer, Tailscale SSH, advertised routes, disabling `exim4` and `containerd` | Convenience and memory savings | Off by default; see variables above |

**Warning:** deploying over the Pi's own Wi-Fi or AP link can drop your SSH session when NetworkManager, hostapd-related units and Cockpit restart. Deploy over wired Ethernet or a console, or pass `SKIP_NM_RESTART=1`.

## Defaults and customizing

- `wlan0` is the WAN (station, hotel Wi-Fi) and `wlan1` is the LAN access point; the AP address is `192.168.200.1/24`. Source of truth: `helper/travelpi-cockpit`; this reference and CONTEXT.md follow it.
- To change roles or the AP subnet, edit the helper constants, `systemd/travelpi-ap-ip`, `systemd/network/travelpi-ap.network.in` (its `Match` is interface-name based), `systemd/wlan1-static-ip.service` and `reset-travelpi-radios.sh` together, then rebuild with `make test`.
- `systemd/modprobe/travelpi-mt7925.conf` blacklists `mt7921u` only for the shared MT7921/MT7925 USB ID `0e8d:7961`. `travelpi-radio-driver` removes it on kernels whose `mt7925u` does not claim the device. Skip that file if your AP adapter is something else.
- Deploy defaults are `PI_USER=pi`, `PI_KEY=$HOME/.ssh/id_ed25519` and `PI_HOST=travelpi.local`. Override per invocation, for example `make deploy PI_USER=me PI_KEY=~/.ssh/my_key PI_HOST=192.168.200.1`.
- Deploy opt-ins, all off by default: `RADIO_SWITCH=1` runs `travelpi-radio-driver` live during deploy (it can unbind the AP radio mid-deploy on a kernel that newly supports `mt7925u`; by default only the boot unit applies it); `SQM_AUTOTUNE=1` enables the 4-hourly CAKE auto-tune timer (each run downloads about 20 MB and uploads about 10 MB through `wlan0`, so leave it off on metered hotel links; without it the timer is disabled and a manual rate still works); `TAILSCALE_SSH=1` runs `tailscale set --ssh --accept-risk=lose-ssh`; `ADVERTISE_ROUTES=192.168.200.0/24,<your ULA /64>` runs `tailscale set --advertise-routes=...` (Tailscale is optional; nothing is advertised unless you set this, and the list must include the ULA from `/etc/travelpi/ula-prefix` if you want it routed). `DISABLE_UNUSED_SERVICES=1` runs `systemctl disable --now exim4.service containerd.service` (about 30 MB freed; off by default so deploy never disables services you did not ask about); `SKIP_NM_RESTART=1` skips the final NetworkManager restart (default is to restart it). Example: `make deploy SQM_AUTOTUNE=1 TAILSCALE_SSH=1 ADVERTISE_ROUTES=192.168.200.0/24`.
- The AP's IPv6 ULA lives in `/etc/travelpi/ula-prefix`: one line holding a /64 such as `fd12:3456:789a:1::/64`. `make deploy` runs `travelpi-ula-init`, which keeps an existing file, migrates the prefix of an already-installed `070-travelpi-ap.network` so a live router keeps its addressing, or otherwise generates a random RFC 4193 prefix (`fd` + 40 random bits), then renders the networkd profile and `radvd.conf` template from it. To rotate it, edit the file and run `make deploy` again (LAN devices renumber). Without the file the helper reports that no ULA is configured instead of claiming IPv6. Set `TRAVELPI_ULA_PREFIX_FILE` to use another path.
- Other hardcoded assumptions you may need to change on different hardware (all are in the code, not configuration):
  - `eth0` is the wired uplink (helper wired-uplink status and `systemd/nm/travelpi-wired-wan.nmconnection`).
  - `usb1` is the root of the USB tree for the OTG hub check behind the USB power/load indicator (`USB_OTG_ROOT` in the helper).
  - The onboard radio is labelled "Pi internal Wi-Fi / Broadcom BCM43430 / SDIO" by a heuristic (the device path contains `mmc1`, or the interface is the WAN). On another board the label may be wrong; it is cosmetic.
  - Resolver and probe constants: Tailscale DNS at `100.100.100.100` (tailnet split DNS), Unbound fallback at `127.0.0.1:5335`, `cloudflare-dns.com` for the encrypted-DNS mode, `google.com` as the default WAN probe target (the Target field overrides it), and `http://neverssl.com/` for the captive-portal hint (plain HTTP on purpose).
  - `ntpsec.service` is expected to be the time service: deploy enables and restarts it, and the clock-sync readiness check assumes a working system clock.
  - Environment overrides that exist: `TRAVELPI_ULA_PREFIX_FILE` (helper and `travelpi-ap-ip`), `TRAVELPI_WAN_IFACE` (the NetworkManager dispatcher `travelpi-adguard-hotel-dns`, default `wlan0`), `TRAVELPI_AUTOTUNE_WAN` (`travelpi-sqm-autotune`, default `wlan0`) and `HOTEL_PROFILE` (`reset-travelpi-radios.sh`, default `HotelWiFi`). The helper itself has no interface override: `WAN`/`LAN` are constants.
- `/etc/travelpi-home-dns` ("domain ip" pairs, optional) adds home-network names to the AdGuard split DNS; it is not created by deploy.

## Pi resource controls

AdGuard Home runs as a Podman Quadlet container with a 192 MiB memory ceiling, a task limit, a restart policy and host networking. `make deploy` installs a rootful system Quadlet, `systemd/system/adguardhome.container`, to `/etc/containers/systemd/`, and, when that file exists, masks the rootless user unit (`systemd/user/adguardhome.container`, still installed) so only one AdGuard runs. The user unit is the fallback for hosts without the system one. PackageKit has a conservative systemd resource guard in `systemd/packagekit/resource-guard.conf`, and is masked by deployment because Cockpit's update polling caused repeated apt metadata storms that exhausted zram. This disables Cockpit's software-update view; temporarily run `sudo systemctl unmask packagekit.service` only during a deliberate maintenance window. The deployment target installs both files; see "What make deploy changes on the host" for everything else it restarts. Tailscale (`tailscaled`) is intentionally kept as a native systemd service rather than a Quadlet: it owns the host's default route and network namespace, so containerizing it would require `--network=host` and add overhead without a resource benefit.

## Radio recovery script

At boot, `travelpi-radio-driver.service` (a oneshot ordered before hostapd) runs the same driver gate as deploy: it removes the blacklist when the kernel cannot drive the AP radio and rebinds a driver if none is bound. `reset-travelpi-radios.sh` is a manual, root-only recovery script for a mis-owned or mis-banded radio pair: it restores the known-good layout (AP on the USB radio `wlan1` at 5 GHz with the AP address, hotel station on the internal radio `wlan0`) and restores the previous `hostapd.conf` if `hostapd` does not come up. It detaches with `setsid` so a brief AP blip cannot kill it, and logs to `/tmp/travelpi-reset.log`. Run it on the Pi (`sudo bash reset-travelpi-radios.sh`) and reconnect to the TravelPi AP afterwards. The hotel profile name is site-specific and is set with the `HOTEL_PROFILE` environment variable (default `HotelWiFi`), for example `sudo HOTEL_PROFILE=MyHotel bash reset-travelpi-radios.sh`. It is deliberately not part of `make deploy` and the helper never invokes it: radio recovery stays an explicit human action.

## Global IPv6 for AP clients

Today AP clients get a per-install ULA address (private, reachable over the tailnet) and no global IPv6 address. A global address needs the upstream network to delegate a prefix to the Pi through DHCPv6 prefix delegation (PD), which the Pi would then route to the AP. That second step is not implemented yet; only the check is (ADR 0007).

**Check whether the network offers PD:** press **Check prefix delegation** on the Network page, or run `sudo /usr/local/libexec/travelpi-cockpit pd` on the Pi. It sends one DHCPv6 SOLICIT on `wlan0` and reports `offered` (with the prefix length), `not_offered` (no server answered, or it answered NoPrefixAvail) or `unavailable` (interface down, no link-local address, not root). It never takes a lease.

**OPNsense:** under Services > DHCPv6 > the segment the Pi joins, enable the DHCPv6 server and set a prefix delegation range and prefix length. The router must itself hold a delegated prefix from its ISP that is large enough to hand out (for example a /56 or /60), and the interface may need to use "Track interface". Menus vary by version; run the check to verify.

**Other routers:** look for "prefix delegation", "DHCPv6-PD" or "downstream /64" settings, and make sure the router has a larger prefix than a single /64 to delegate.

Hotels almost never offer PD, so expect `not_offered` there; this path is for a home or other network you control.

Alternatives considered and not chosen: NDP proxying (fragile, per-address, and breaks with privacy addresses and without upstream cooperation) and NAT66 (breaks end-to-end addressing and is non-standard).

## Helper boundary and protocol

The UI talks to a root-owned executable, installed by `make deploy`, at:

```text
/usr/local/libexec/travelpi-cockpit
```

The helper may be a compiled program or a carefully reviewed script, but it must be owned by `root:root`, have a non-writable parent directory, and have a fixed interpreter and absolute paths if it is a script. A one-shot helper is preferred; it does not need to run as a long-lived daemon. The helper is the only component that should translate the small action vocabulary into NetworkManager, hostapd, dnsmasq, `tc`, systemd, or reboot operations.

The read-only `probe` command performs one bounded, interface-bound `/usr/bin/curl` HTTP request over `wlan0` against a target host. It accepts an optional target argument (a hostname or IPv4 address); when omitted it defaults to `google.com`, so the check exercises both DNS resolution and Internet reachability. The helper validates the target strictly (no scheme, path, port, or shell metacharacters) and rejects anything invalid with the error `invalid_probe_target` instead of probing. It does not accept a URL, arbitrary command input, or run a speed test. Its JSON result reports `ASSOCIATION_FAILED`, `NO_DHCP`, `NO_ROUTE`, `NO_DNS` (target could not be resolved), `CAPTIVE_PORTAL`, `INTERNET_OK`, or `NO_INTERNET`; `CAPTIVE_PORTAL` is reported for HTTP 511 or a 2xx/3xx response that redirects to a private, link-local, loopback or CGNAT (100.64.0.0/10) address (IPv4 or IPv6 literal), or to a hostname outside the probed host's registrable domain (compared by its last two labels, so `google.com` to `www.google.com` is not a portal but a redirect to `portal.hotel.example` is; multi-part suffixes such as `co.uk` are a known blind spot and an IP-literal probe target skips the hostname test). This is a heuristic: a portal that answers 200 with its own page and no redirect cannot be detected. It never automates login. The Internet card runs this probe automatically on load and on a recurring timer, and also lets the user change the target (domain or IP) through the **Target** field, which re-runs the probe when changed. The probe is invoked through `cockpit.spawn` with the target as a fixed argv element.

TravelPi does not persist hotel MAC identities or hotel profile records. The hotel Wi-Fi form keeps connection credentials in memory for the attempt, while the current WAN MAC remains visible and copyable and manual MAC cloning remains an explicit confirmed action. Existing NetworkManager connection profiles remain authoritative.

The read-only status response also reports detected radio hardware and transport, the DNS stack, optional encrypted-DNS mode, safe IPv6 state, CAKE/SQM state, WAN identity, normalized secure-tunnel summaries (provider state, tunnel addresses, exit node, peer count, routes, and handshake/transport details where available), Tailscale authentication state (`needs_login` and the `AuthURL` when the tunnel requires sign-in, surfaced as a login link and an optional authkey field), and Pi health telemetry (temperature, load, swap, and power-throttle flags) for the compact Quick Settings surface. Missing radio interfaces are marked absent so the UI can hide them. The fixed `scan` command can return sanitized nearby SSIDs and signal facts for explicit hotel setup; it never returns credentials or auto-connects. The root-only `pd` command sends one DHCPv6 SOLICIT with an IA_PD option on `wlan0` and only reads the answer (it never sends a REQUEST, so no lease is taken) to report whether the upstream network would delegate an IPv6 prefix; see Global IPv6 for AP clients. Readiness evidence reports wired-uplink, transient-profile, AP-profile, and rollback support without applying them. AdGuard Home's full administration remains at its own GUI.

The JavaScript must invoke fixed argv arrays through `cockpit.spawn`, for example:

```js
cockpit.spawn([
    "/usr/local/libexec/travelpi-cockpit",
    "status",
], { superuser: "try", err: "message" });
```

For an action, the UI starts the fixed `action` subcommand and sends one JSON request as UTF-8 on stdin. It may use Cockpit's stdin/input API; the request must not be placed in a shell command, an argument containing a password, or an environment variable:

```js
const process = cockpit.spawn([
    "/usr/local/libexec/travelpi-cockpit",
    "action",
], { superuser: "try", err: "message" });
process.input(JSON.stringify(request) + "\n");
```

The exact Cockpit API spelling for sending process input can vary with the package's JavaScript style, but the wire contract is the same:

- `status` takes no stdin and writes exactly one JSON response object to stdout.
- `action` reads exactly one newline-delimited JSON request from stdin and writes exactly one JSON response object to stdout.
- stdout is machine-readable JSON only. Human diagnostics go to stderr and must not contain passwords or other secrets.
- Malformed JSON, unknown fields, unknown actions, extra input, invalid values, and missing confirmation are rejected with a non-zero exit status and a safe error response where possible.
- The helper must never echo the request, password, NetworkManager secret, or a command line. It should avoid writing secrets to logs, temporary files, environment variables, or persistent connection profiles.

Successful responses have this shape:

```json
{
  "ok": true,
  "action": "set_cake_rate",
  "message": "CAKE rate updated",
  "status": {}
}
```

`status` is optional after an action; if present it uses the same schema below. A failure should use a stable, non-secret error code and short message:

```json
{
  "ok": false,
  "error": {
    "code": "invalid_request",
    "message": "The requested channel is not allowed"
  }
}
```

### Allowed action requests

Every request is `{"action": ..., "confirm": true, ...fields}`. The helper rejects a missing confirmation, unknown actions and unknown fields. Confirmation in the browser is a safety affordance, not an authorization boundary; the helper enforces it too. The authoritative list is `ACTION_FIELDS` in `helper/travelpi-cockpit`; `tests/action-contract-alignment.py` keeps it in step with `travelpi-contracts.ts`, so the table below is a summary, not a second source of truth.

| Action | Request fields (plus `confirm`) | Helper-side validation |
| --- | --- | --- |
| `connect_hotel` | `ssid`, `password`, `hidden` | SSID 1-32 chars, password at most 128, no newlines; optional boolean `hidden` (anything else is refused `invalid_hidden`) adds `hidden yes` to the `nmcli` connect for a non-broadcast SSID. `wlan0` only. Password goes to `nmcli --ask`, never argv; NetworkManager keeps its own profile and a never-activated profile created by a failed attempt is deleted. |
| `apply_mac_clone` | `mac`, optional `mode` | `mode` is `specific` (default, needs a valid unicast MAC), `random` (NetworkManager generates one) or `default` (reset to hardware). `wlan0` only; the previous setting is restored if connectivity breaks. |
| `set_ap_radio` | `band`, optional `channel` | `band` is `2.4ghz`, `5ghz` or `6ghz`. A channel must be one the AP radio reports (DFS excluded); `6ghz` is refused with `radio_capability_missing` without host evidence. Applies to the AP radio only. |
| `set_ap_identity` | `ssid`, `passphrase` | SSID 1-32 chars, WPA2-PSK passphrase 8-63 chars. Never echoed; previous identity restored on failure. |
| `set_wan_band` | `band` | `auto`, `2.4ghz`, `5ghz` or `6ghz` on the active WAN profile; verified with the WAN probe and restored on failure. Refusals: `wan_not_connected`, `band_unsupported`, `radio_capability_missing` (`6ghz`). |
| `set_cake_rate` | `rate_kbit` | Finite value in the helper's safe range (a unit suffix such as `mbit` is accepted); no raw `tc` arguments. |
| `set_sqm_mode` | `mode` | `auto`, `manual` or `off`. |
| `restart_services` | `targets` | A non-empty list of `ap` and/or `sqm` only; mapped to fixed units. |
| `vpn_toggle` | `provider`, `enabled` | `provider` is `tailscale` or `wireguard`; `enabled` must be a boolean. OpenVPN is status-only. |
| `tailscale_auth` | `authkey` | Required; passed through a 0600 temporary file, never argv. Blank is refused with `authkey_required`. |
| `wake_peer` | `target` | A tailnet peer name or address (`[A-Za-z0-9][A-Za-z0-9.-]{0,63}`); sends a Tailscale wake-on-LAN packet. |
| `set_dns_stack` | `service`, optional `upstream` | `service` is `adguard` or `unbound`; `upstream` is IPv4 nameservers. Restores the filtered stack if Unbound cannot take over. |
| `set_ipv6` | `mode` | `on` or `off` for router advertisements. Refused as unavailable when the networkd AP profile or the ULA prefix is missing. |
| `set_cpu_governor` | `governor` | `conservative`, `ondemand` or `performance`. |
| `reclaim_memory` | (none) | Syncs and drops kernel page caches; never stops services or kills processes. |
| `wan_flip` | `wan` | Radio role swap. Refused with `unavailable` unless readiness evidence reports role switching supported (ADR 0002, 0004). |
| `reset_radios` | (none) | Repairs the canonical layout (AP on the 5 GHz-capable radio, WAN on the other) and restores `hostapd.conf` if hostapd fails to start. |
| `reboot` | (none) | Runs `systemctl reboot`; the Cockpit session will disconnect. |

The read-only commands are `status`, `probe [target]`, `scan` (root), `pd` (root), `readiness` and `portal [fresh]`. The helper may add stronger local policy and must not silently broaden the action vocabulary.

### Status response

The dashboard expects a sanitized `status` object containing these read-only areas. Values can be marked `unknown` when the platform cannot determine them; the helper must never include credentials or NetworkManager secret data.

```json
{
  "ok": true,
  "status": {
    "wan": {
      "interface": "wlan0", "state": "connected", "ssid": "hotel-wifi",
      "ip": "192.0.2.10/24", "gateway": "192.0.2.1", "signal_dbm": -58,
      "freq": 5180, "band": "5ghz", "band_setting": "auto"
    },
    "ap": {
      "interface": "wlan1", "state": "up", "ssid": "TravelPi",
      "band": "2.4ghz", "channel": 6, "ip": "192.168.200.1/24", "wifi6": false
    },
    "currentWanMac": "02:11:22:33:44:55",
    "wanMacClone": { "active": false, "address": null },
    "clients": {
      "count": 1,
      "items": [ { "mac": "02:aa:bb:cc:dd:01", "ip": "192.168.200.20", "hostname": "phone" } ]
    },
    "defaultRoute": { "interface": "wlan0", "gateway": "192.0.2.1" },
    "cake": { "interface": "wlan0", "state": "active", "mode": "manual", "qdisc": "cake", "rate": "25Mbit" },
    "services": { "NetworkManager": "active", "hostapd": "active", "dnsmasq": "active", "sqm": "active" }
  }
}
```

This example is abridged and the values are illustrative. The real response also carries `dnsStack`, `ipv6`, `vpn`, `wired`, `readiness`, `radioInventory`, `health`, network-health fields, and more keys inside the areas shown (for example `services.unbound` and `services.adguard`). `spoofedWanMac` and `hardware` are deprecated aliases. The authoritative shape is `status()` in `helper/travelpi-cockpit` and the types in `travelpi-contracts.ts`.

The UI presents these areas as read-only cards: WAN on `wlan0`, the TravelPi AP on `wlan1`, the current WAN MAC, connected clients, the default route, CAKE/qdisc, and service status. The helper owns the truth of the status values; the browser must not infer privileged state by running arbitrary probes, but may invoke the fixed `probe` command above with a user-editable target.

## Host requirements

`make deploy` installs TravelPi's own units and helper but does not install these base packages. The image administrator is responsible for them and for the exact unit names and paths on the image in use.

- **NetworkManager:** manage the hotel/uplink connection on `wlan0`. Avoid two managers fighting over the same interface. If a transient profile is used for hotel credentials, ensure it is not saved as a permanent profile and is removed on disconnect or failure.
- **hostapd:** own the TravelPi AP on `wlan1`. The helper should update only the allowlisted AP settings and restart the known AP unit when requested. The radio must support the selected 2.4 GHz channel 6 or 5 GHz channel 36 mode; Wi-Fi 6 support is hardware/driver/hostapd dependent; `ap.wifi6` is read from `ieee80211ax=1` in `hostapd.conf` and falls back to the radio's HE capability when that file is unreadable.
- **dnsmasq:** provide the AP-side DHCP/DNS service on `wlan1` with a fixed, root-owned configuration. Its lease data is a source for the client card, but it is not a substitute for validating clients through the intended local status commands.
- **SQM/CAKE:** provide a known SQM unit and a CAKE-capable kernel/`tc` installation. The helper should change a bounded rate in the managed SQM configuration or a fixed `tc` operation, then report the resulting qdisc. It must not accept arbitrary qdisc expressions.
- **systemd:** keep hostapd, dnsmasq, and SQM unit files/configuration root-owned. The helper may restart only fixed unit mappings such as the image's AP and SQM units; it should use an absolute `systemctl` path and a controlled environment. Do not allow a web user to edit an `EnvironmentFile`, unit file, or helper dependency.
- **sudo:** Cockpit may use sudo for `superuser: "try"` on systems configured that way. If a sudoers rule is needed, grant only the exact helper entry and the required administrator group; do not grant a shell, `systemctl`, `nmcli`, `tc`, or a wildcard command directly to the Cockpit web user.
- **polkit:** on systems using polkit/pkexec, authorize only the intended Cockpit administrator group to run this helper as root. The package does not install a polkit rule. Review the rule against the distribution's Cockpit bridge and polkit versions, and fail closed when the privilege request is denied.

The helper uses absolute executable paths, bounded timeouts and clear failure responses. Service restarts and reboot are intentionally disruptive and should be logged by the host in the normal system audit trail, without logging secrets.

## Security and threat model

### Assets and trust boundaries

The main assets are the hotel Wi-Fi credential, the router's network-control functions, the AP's connected-client information, and the availability of the Pi. The relevant boundary is:

```text
Cockpit browser session
    -> Cockpit authentication/session channel
    -> Cockpit bridge and privilege escalation
    -> root-owned travelpi-cockpit helper
    -> fixed NetworkManager/hostapd/dnsmasq/tc/systemd operations
```

Cockpit authentication is the user-authentication layer. This package adds no credentials and assumes Cockpit itself is correctly configured with TLS/access controls, current security updates, an appropriate administrator group, and no unnecessary public exposure. A Cockpit login alone does not make a user root.

### Controls and assumptions

- **Sudoers rule installed by deploy:** `/etc/sudoers.d/travelpi-adguard` lets the deploy user (`PI_USER`) run `cat` as root on exactly `/opt/adguardhome/conf/AdGuardHome.yaml` (path-pinned, `NOPASSWD`), so the AdGuard config, which may hold password hashes, is readable by that user. It is validated with `visudo -cf` before install. Remove the file if you do not want it; the AdGuard card then cannot read upstream settings.
- **Privilege:** privileged calls use `cockpit.spawn` with `superuser: "try"`. This lets Cockpit request the configured elevation path and report a denial; it does not grant permission by itself. Sudoers/polkit and helper file permissions must enforce which users can perform root actions.
- **Command injection:** the UI passes a fixed executable and fixed subcommands as an argv array. There is no arbitrary command execution endpoint. It does not interpolate shell text, use `sh -c`, or evaluate browser-provided JavaScript. The helper must retain this boundary: parse a strict JSON schema, reject unknown fields, map each allowed action to fixed commands, and never treat a field as a program, path, unit name, or shell fragment.
- **Helper validation:** the helper is the security boundary for input. It validates UTF-8/length limits, MAC syntax and type, the two allowed AP modes, bounded CAKE rates, fixed service targets, confirmation flags, interface identities, and operation timeouts. It should re-check state after changes and return sanitized errors. Browser-side validation is only usability support.
- **Password handling:** the hotel password is held in the password input only until submission and must not be copied into localStorage, cookies, URLs, telemetry, status objects, confirmation text, logs, command-line arguments, or environment variables. The UI should clear the input after the request is sent and on cancel/close. The helper must not echo it or store it in a permanent NetworkManager profile; use an in-memory/transient connection or reject the request when that guarantee is not possible. This does not protect a Pi or browser that is already compromised.
- **Information disclosure:** client MAC/IP/hostname, SSID, route, and service state are operational data. Cockpit authentication and network controls protect them; the helper should return only the fields required by the cards and avoid sensitive diagnostics. Passwords and secret material are never part of status.
- **Disruption and abuse:** every mutating action requires an explicit confirmation in the UI, and the helper independently requires `confirm: true`. The reboot and service-restart operations need stronger warning text. Confirmation prevents mistakes, not a malicious authorized user; rate limits, group membership, host audit policy, and physical/network access controls remain administrator responsibilities.
- **Tampering:** root ownership, non-writable parent directories, restrictive service/configuration permissions, package integrity checks, and normal OS patching protect the helper and its dependencies. A user who can replace the helper, its interpreter, its unit files, or its polkit/sudo rules can bypass this design and is already effectively root.

### Out of scope

This UI is not a general NetworkManager editor, firewall editor, full VPN manager, hostapd configuration editor, credential vault, or remote fleet deployment tool. It intentionally cannot express arbitrary routes, qdiscs, commands, service names, or configuration files. The narrow Tailscale authentication action is a reviewed, fixed trigger for Tailscale's own `login`/`up` flow, not a general VPN configuration editor. The separately installed helper must remain small, reviewed, and specific to the TravelPi image.

Read-only status is refreshed through the helper's `status` operation and is not a promise that the browser can repair an unhealthy service. If the helper is unavailable or elevation is denied, the UI shows a clear error and leaves controls unavailable.

## Config backups

A daily timer writes an archive under `/var/lib/travelpi/backups` containing NetworkManager profiles, staged AdGuard config, unit files, hostapd, dnsmasq, Unbound and DNS-mode config, `/etc/travelpi` (including the ULA prefix), `/etc/travelpi-home-dns`, the networkd AP profile and its drop-ins, and the Tailscale node key (ADR 0003). The authoritative list is the `BEGIN/END BACKUP PATHS` block in `systemd/travelpi-config-backup`; the Makefile `RESTORE_PATHS` mirrors it. NetworkManager profiles can hold Wi-Fi secrets, so treat the archive as sensitive: `make backup-pull` saves it locally with mode 0600, and `make restore RESTORE_ARCHIVE=...` puts it back after a re-image and `make deploy`. Restore prints the archive listing and stops unless you pass `CONFIRM=1`; it then rejects the whole archive if any member is outside the paths the backup script writes (or is a link, device or contains `..`), extracts from a private temp dir, and copies the staged `/etc/travelpi-AdGuardHome.yaml` to `/opt/adguardhome/conf/AdGuardHome.yaml`.

## Status and limitations

- Validated only on a Raspberry Pi Zero 2 W with a USB Wi-Fi AP radio on Raspberry Pi OS (Debian 13). Other boards, radios and OS releases are unverified.
- The USB AP radio family may need a newer kernel for 6 GHz; the driver switch refuses honestly when the kernel does not claim the device (ADR 0005).
- The features listed under "What it does not do" are not implemented.
- Contributions and bug reports are welcome. There is no warranty; this software reconfigures network services as root, so read it before you run it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup, the `make test` and `make check` gates, and the project guardrails.

## Security

Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md); do not open a public issue for them.

## License

Released under the [MIT License](LICENSE).
