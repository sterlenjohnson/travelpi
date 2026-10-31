> Superseded in part (2026-10-30): the ULA prefix named below was inside Tailscale's
> own block; it is now per-install in `/etc/travelpi/ula-prefix` (ADR 0006 Update).

# PLAN — ULA fix, radio facts, AP control, scan-select, portal

Researched 2026-10-30 against a live reference Pi (read-only
probes) and three isolated repo research passes.

## Status (2026-10-30): ALL PHASES A-F IMPLEMENTED, make check green (22 checks + harness gate)

- A ✅ keeper + helper v4-scoped flush, ULA gateway, link-local recovery,
  RA-daemon restarts (systemd-networkd per ADR 0006 after the radvd
  privsep discovery); tests/ap-address-guard.py (mutation-verified).
- B ✅ helper `portal [fresh]` CLI, hotel.html portal row (link + re-check),
  URL scheme-validated; frontend + CLI tests.
- C ✅ scan rows show band/channel/security, click prefills SSID with
  security-aware password help; WEP classified; frontend tests.
- D ✅ modprobe blacklist + travelpi-radio-driver switch with
  restore-to-mt7921u; deploy wiring; journal matcher counts mt7925;
  tests/radio-driver-switch.py.
- E ✅ channel picker validated against iw supported_channels (DFS
  excluded); 6 GHz gated on host evidence; coordinator copy names the
  channel; helper + coordinator + frontend tests.
- F ✅ set_ap_identity (17th action): helper restore-on-fail + secret
  hygiene tests, copy never echoes the passphrase, network.html form,
  payload/clear tests.

## Host findings (verified on the Pi, 2026-10-30)

1. **No ULA on LAN clients — repo-side root cause.** `wlan1` has **no IPv6
   address at all**, not even link-local. `systemd/travelpi-ap-ip` line 15
   runs `ip addr flush dev "$iface"`, which flushes IPv6 addresses; the
   kernel regenerates link-local only on an admin state change, never after
   a flush. radvd is active and its `/etc/radvd.conf` prefix block is
   correct (`AdvOnLink on; AdvAutonomous on`), but RFC 4861 requires RAs to
   be sourced from a link-local address, so every advertisement is invalid
   and clients SLAAC nothing. The helper's `apply_radio_layout` (line 947)
   flushes the same way on every role apply.
2. **Secondary cause:** `tailscale status --json` currently reports
   `Ads: []` — the Pi advertises **no routes at all** right now (the
   v4 + v6 advertisements from 2026-10-28 are gone, likely from the
   tailscaled re-auth). Even with SLAAC fixed, the ULA prefix is not
   tailnet-routed until `--advertise-routes` is re-applied and approved.
3. **6 GHz band — Wi-Fi 6E stick, driven by the wrong driver.** The AP
   radio is USB `0e8d:7961`, a **shared USB ID** used by both MT7921AU and
   MT7925AU (Wi-Fi 6E). On this Pi the **`mt7921u`** driver claimed it
   (dmesg 16.1s), which exposes only 2.4/5 GHz. The host already has
   everything needed for 6E: `mt7925u.ko.xz` is in the 6.12.75 kernel,
   `/lib/firmware/mediatek/mt7925/` carries the MT7925 firmware
   (`WIFI_RAM_CODE_MT7925_1_1.bin` + MCU patch), and hostapd 2.10 supports
   6 GHz AP (`he_6ghz=1`). OpenWrt shows the 6 GHz band on the same stick
   (user report) because it binds the ID to mt7925u. Confirmation probe
   after the switch: `sudo iw phy phy1 info | grep Band` should show Band 3.
4. **AP today:** SSID `TravelPi`, `hw_mode=a channel=36`, WPA — configured
   only by band profile (2.4→ch6, 5→ch36). No SSID/password editing, no
   channel choice.
5. **Second ULA cause (found live at deploy, 2026-10-30):** radvd 2.20's
   privsep sandbox resolves NO interface on this host — the sender child
   logs `"wlan1" not found: No such device` (`setup_iface=-1`), identically
   for `lo` — so zero RAs ever left wlan1 while the unit read `active` and
   `--configtest` passed. RA layer switched to systemd-networkd v257
   (ADR 0006): `systemd/network/travelpi-ap.network`; deploy enables
   networkd, disables radvd; keeper/helper restart `systemd-networkd`.
   Verified post-deploy: 9 RAs in 45 s on wlan1, prefix
   `fd7a:115c:a1e0:200::/64, Flags [onlink, auto]` + route `64:ff9b::/96`,
   sourced from the interface link-local.
6. **Finding 2 correction:** v1.102 `Self.Ads` is a deprecated field (its
   emptiness alarmed a false negative). With the privileged socket,
   `Self.PrimaryRoutes = ['192.168.200.0/24']`: the v4 advertisement is
   applied, `tailscale ping <home-router-ip>` pongs off the home subnet router and a
   plain ping runs ~23 ms. The new v6 advertisement is in prefs, awaiting
   admin-console approval. Tailnet Lock is OFF (the all-zero
   `NetworkLockKey` is the disabled state).

## Design

### Phase A — make the ULA real (helper + unit, host behavior)
- `systemd/travelpi-ap-ip`: flush IPv4 only (`ip -4 addr flush`), add the
  gateway address `fd7a:115c:a1e0:200::1/64` on the AP iface, and recover
  link-local when missing via the `disable_ipv6` 1→0 toggle (standard
  kernel regen trick).
- Helper `apply_radio_layout`: same IPv4-scoped flush + v6 gateway add.
- Projection/status: surface `ap_ipv6_gateway` (presence check) so the
  dashboard shows the bridge state honestly.
- Guards: shell/unit + helper tests asserting IPv4-scoped flush and the
  v6 add (pattern of `tests/deploy-file-list.py`).
- Human host steps after deploy: `sudo tailscale set
  --advertise-routes=192.168.200.0/24,fd7a:115c:a1e0:200::/64
  --accept-routes --accept-dns=false`; restart radvd; verify a client
  gets `fd7a:115c:a1e0:200::*` and console-approve the v6 route.

### Phase B — captive-portal affordance (display-only, per guardrail)
- Helper `portal_status`: include the validated redirect URL (scheme
  allowlist http/https, host must be in the private ranges it already
  matches) in the payload.
- Projection: expose `portal_url`.
- UI: portal warning becomes a link to the portal URL + a "Re-check
  portal" button that forces a fresh probe (cache-bypass flag on the
  cached command). No automation, per AGENTS.md guardrail.

### Phase C — scan WAN, pick, connect
- Helper `parse_wifi_scan`: add `frequency`, `channel`, `security`
  ("open" | "wep" | "wpa" from iw `capabilities:`/`ssid:` block).
- Projection: normalize scan entries (band via existing 5925 MHz
  threshold rule); sort keeps signal-first.
- UI (`hotel.html`): scan rows become buttons — clicking prefills the
  connect form SSID, shows "WPA password required" vs "Open network"
  (password field hidden for open), focuses password. Scan results gain
  band + signal bars + security icon. Existing "scan and pick a network"
  helper docstring becomes true.

### Phase D — MT7925 (6E) driver switch
- Deploy installs `/etc/modprobe.d/travelpi-mt7925.conf` blacklisting
  `mt7921u`, so the shared ID `0e8d:7961` binds to `mt7925u`.
- Deploy switch step (guarded, one-time): `modprobe mt7925u`; unbind
  `1-1.2:1.0` from `mt7921u`; `modprobe -r mt7921u`; rebind via
  `drivers/usb/bind`; verify a phy appears and hostapd comes up. On
  failure: drop the blacklist file, rebind under `mt7921u`, restart
  hostapd — the AP returns to the proven 2.4/5 profile (restore-on-fail).
- Helper: journal matcher counts `mt7925` flap events alongside mt7921
  (line 887); `radio-watch` already rebinds at the `usb` driver level, so
  no ladder change.
- 6 GHz AP profile when bands prove it: `hw_mode=a`, 6 GHz channel,
  `ieee80211ax=1`, `he_6ghz=1`. Band availability is decided from
  `iw phy` output in status, never hardcoded.

### Phase E — AP channel control
- Contract: `set_ap_radio` payload gains optional `channel`.
- Helper: validate the requested channel against `supported_channels`
  parsed from `iw phy info` per band (hardware truth, not a guess table);
  2.4: 1–11; 5 GHz non-DFS 36–48, 149–165; 6 GHz only if phy reports
  Band 3. `interface_hardware` gains `supported_channels` per band.
- UI (`network.html` + advanced): band select + channel select populated
  from `supported_channels`; 6 GHz option appears only when the host
  reports the band.
- Copy: "Move the LAN access point to 5 GHz channel 149 …".

### Phase F — AP name & password (`set_ap_identity`)
- Contract: `set_ap_identity: { ssid: string(1–32), passphrase:
  string(8–63) }`.
- Helper: write `ssid=` + `wpa_passphrase=` into hostapd.conf (0600,
  netdev), back up the conf, restart hostapd, verify AP active, restore
  on failure (exact `set_ap_radio` restore pattern). Passphrase exists
  only in argv + the conf write; never read into status, never displayed,
  never in localStorage.
- UI: AP form gains SSID + new-passphrase fields (write-only inputs,
  never prefilled); confirm copy names the SSID, never the passphrase.
- Status: `ap_ssid` already projected; verify no passphrase leak path.
- Follows the repo's 8-item new-action checklist (contracts, coordinator
  copy, UI, payload builder, `ACTION_FIELDS`, status payload, hostapd
  restore, tests + alignment guard).

## Order & rationale
A (live bug) → B (small, independent) → C (presentation-heavy,
independent) → D (driver switch; unlocks the band truth for E) → E
(channels, incl. 6 GHz when proven) → F (credentials, builds on E's
hostapd writer). Each phase ends with `make check` green and its own
commit.

## Deliberate non-goals
- No 6 GHz AP option in the UI until `iw phy` reports the band (the
  driver switch is verified before any 6 GHz profile is offered).

## Residuals recorded, not fixed
- `070-travelpi-ap.network` (and the legacy `radvd.conf`) advertise on a
  hardcoded interface name; a radio role swap that moves the AP to the
  other interface needs the config regenerated (keeper restarts the RA
  daemon, so it recovers addressing, not the interface name). Follow-up
  issue.
- Portal detection identifies the portal via a redirect to a private
  address; a portal served on a public hostname is reported online
  (display-only hint, documented limitation).
- No captive-portal automation (guardrail).
- No open-security AP option (WPA2-PSK stays the only mode).
