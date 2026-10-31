# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub: on this repository open the **Security** tab and choose **Report a vulnerability** (GitHub private vulnerability reporting / security advisories). Do not open a public issue or pull request for a suspected vulnerability, and do not include real hotel credentials, Wi-Fi passphrases, auth keys or backup archives in a report.

If the Security tab offers no reporting option, open a public issue that says only that you need a private channel, with no technical detail, and a maintainer will arrange one.

Useful details: the commit or release, what you did, what you expected, what happened, and whether the problem needs a Cockpit login, a local shell or network access.

## What is in scope

- The root-owned helper `helper/travelpi-cockpit`: input validation, the action allowlist, confirmation handling, secret handling (passwords and keys passed over stdin or 0600 temporary files, never argv or logs), and any way to make it run a command, path or unit the allowlist does not name.
- The deploy and restore recipes in the `Makefile`, the sudoers drop-in they install, and the scripts and units under `systemd/` that run as root.
- Handling of secrets: any path by which a hotel password, hotel MAC identity, Tailscale auth key or config backup content is persisted, logged, echoed to the browser, or exposed to a less-privileged user.
- The static Cockpit package: script injection, a CSP bypass, or loading remote assets.

## What is out of scope

- Compromise that already requires root on the Pi, or the ability to replace the helper, its units or its sudoers/polkit rules (that user is already effectively root).
- Weaknesses in Cockpit, NetworkManager, hostapd, dnsmasq, AdGuard Home, Tailscale, Podman or the OS itself; report those upstream.
- A Cockpit session that is exposed to the public Internet or lacks TLS or sensible access control: this package assumes Cockpit is configured correctly.
- Physical access, a malicious authorized administrator, denial of service from someone who can already reach the Pi's AP, and issues on hardware or OS releases other than those listed under Status in the README (reports are welcome but may be handled as ordinary bugs).
- Findings that rely on a modified copy of the code or on running `make deploy` against a host you do not control.

## Response

This is a volunteer-maintained project. We aim to acknowledge a report within about a week and to keep you informed, but we cannot promise a fix timeline or a bounty. Please allow a reasonable period for a fix before public disclosure; we will credit reporters who want credit.

## Security posture

- The helper accepts a fixed, allowlisted action vocabulary with strict fields and requires `confirm: true`; it never accepts a command, unit name or path from the browser, and it is not a general shell.
- TravelPi does not persist hotel credentials, passwords or hotel MAC identities. Remembered SSIDs are the only convenience hint, and NetworkManager profiles stay authoritative.
- No captive-portal login automation, and no capability is claimed that the host has not demonstrated.
- The Cockpit package directory is root-owned and not writable by the web user; the package is plain static files under a same-origin CSP, with no remote assets.
- Config backups can contain Wi-Fi secrets and the Tailscale node key; they are root-only on the Pi and `make backup-pull` saves them with mode 0600. Treat them as sensitive.
- `make deploy` installs a sudoers rule that lets the deploy user read the AdGuard config as root, pinned to that one path. See the README sections "What make deploy changes on the host" and "Controls and assumptions".

See also the threat model in the README.
