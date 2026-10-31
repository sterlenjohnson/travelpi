# ADR 0003: Config backup archives credential material under root-only discipline

## Status

Accepted, as a recorded exception to ADR-0001's "credentials are not copied into TravelPi storage".

## Decision

`travelpi-config-backup` snapshots the hand-built host configuration to `/var/lib/travelpi/backups`: NetworkManager system connections (which contain hotel PSKs), `/var/lib/tailscale` (the tailnet node key), the AdGuard Home YAML (admin auth hash), `/etc/hostapd/hostapd.conf` (the AP passphrase), systemd units, sysctl/sudoers drops-ins, and the SQM environment. The rest of the hand-built config set is in scope too, so a rebuilt card needs nothing from memory: `/etc/dnsmasq.d/travelpi.conf`, `/etc/default/travelpi-dns`, `/etc/default/travelpi-power-profile`, `/etc/unbound/unbound.conf.d/travelpi-front.conf`, the networkd AP profile and its drop-in directory (`070-travelpi-ap.network` and `.network.d/`, which holds the `ra-off.conf` choice), `/etc/travelpi-home-dns`, and `/etc/travelpi/` (the per-install ULA prefix). Only paths that exist are archived (`--ignore-failed-read`).

The archived paths are listed once, between the `BEGIN BACKUP PATHS` / `END BACKUP PATHS` markers in `systemd/travelpi-config-backup`; `make restore` derives its extraction allowlist from that block, so the backup and the restore cannot drift apart. A brownout-killed SD card must mean re-image + `make deploy` + `make restore`, not archaeology.

The archive is root-only and the pull is deliberate:

- the backup script runs `umask 077`, sets the directory 0755 and the archive 0600;
- filenames carry only a timestamp, so the directory stays listable and `make backup-pull` can find the newest archive as the login user;
- the archive content is read through `sudo`, over a PTY so sudo can prompt for a password, base64-encoded because a PTY rewrites `0x0A` as `0x0D 0x0A`; the pull decodes it, lands it 0600, and verifies it is a readable tarball;
- nothing in the Cockpit package, the helper's status payload, telemetry, or logs contains credential material.

## Rationale

The domain rule forbids TravelPi from *newly* persisting hotel credentials: the dashboard must not create its own credential store, and NetworkManager profiles remain authoritative. The daily snapshot is not a new store — it is a copy of the authoritative profiles that already exist on the card, and the card is the failure domain the backup exists to survive.

Making it world-readable would be a genuine escalation, so the discipline is the point: root-only on the Pi, password-mediated and verified on the Mac, and 0600 locally.

## Consequences

- `/var/lib/travelpi/backups` is 0755 root; archives are 0600 root. Local pulls are 0600 and contain live credentials: treat `backups/` as secret material and delete it when a Pi is decommissioned.
- `tests/config-backup.py` enforces the mode discipline and the pull contract (sudo, base64 decode, tar verification) so a future edit cannot silently widen access.
- Anyone who can read the archive can read hotel PSKs and the tailnet node key. That is accepted for the operator's own administrator account; it is not accepted for any web-facing surface.
