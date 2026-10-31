#!/usr/bin/env python3
"""AP addressing contract: the IPv6 bridge stays addressable on the AP radio.

The 2026-10-30 ULA incident: `ip addr flush` in the AP keeper wiped the
interface's IPv6 link-local address (the kernel regenerates it only on an
IPv6 enable edge), which made every router advertisement invalid, so
LAN clients never received a ULA address. The behavior is pinned elsewhere:

- tests/script-ap-keeper.py runs systemd/travelpi-ap-ip under shims (IPv4-only
  flush, ULA gateway from the prefix file, link-local toggle before the gateway
  add, never a networkd restart, no mutation on healthy watch ticks).
- tests/radio-layout.py runs the helper's apply_radio_layout through the HOST
  seam (IPv4-only flush, gateway add, link-local recovery, networkd restart on
  the success and restore paths).

What stays here are the static contracts those cannot see:

- no source hardcodes Tailscale's ULA block, and the keeper parses as POSIX sh;
- the unit runs the keeper in watch mode;
- RA layer: radvd 2.20's privsep sandbox resolves no interface on this
  host (2026-10-30: "wlan1" not found: No such device, even for lo), so
  deploy installs systemd/network/travelpi-ap.network for systemd-networkd
  (prefix + NAT64 route + AcceptRA=no) and disables radvd.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEPER = (ROOT / "systemd" / "travelpi-ap-ip").read_text(encoding="utf-8")
HELPER = (ROOT / "helper" / "travelpi-cockpit").read_text(encoding="utf-8")
UNIT = (ROOT / "systemd" / "wlan1-static-ip.service").read_text(encoding="utf-8")
TEMPLATE = (ROOT / "systemd" / "network" / "travelpi-ap.network.in").read_text(encoding="utf-8")
INIT = ROOT / "systemd" / "travelpi-ula-init"
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")

# Generic per-install example; the real prefix is rendered at deploy time.
ULA_PREFIX = "fd12:3456:789a:1::/64"
ULA_GATEWAY = "fd12:3456:789a:1::1/64"
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


# --- keeper script -------------------------------------------------------
check("fd7a:115c:a1e0" not in KEEPER + HELPER + TEMPLATE,
      "no source may hardcode Tailscale's ULA block")
sh = subprocess.run(["sh", "-n", str(ROOT / "systemd" / "travelpi-ap-ip")],
                    capture_output=True, text=True)
check(sh.returncode == 0, "keeper must parse as POSIX sh: " + sh.stderr.strip())

# --- unit drives the keeper in watch mode --------------------------------
check("ExecStart=/usr/local/libexec/travelpi-ap-ip watch" in UNIT,
      "wlan1-static-ip.service must run the keeper in watch mode")

# --- RA layer: systemd-networkd advertises, radvd stays disabled ---------
# Render the template the way deploy does, with a generic prefix.
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import tempfile
tmp = Path(tempfile.mkdtemp(prefix="travelpi-ap-guard-"))
(tmp / "ula-prefix").write_text(ULA_PREFIX + "\n")
rendered = subprocess.run(
    ["sh", str(INIT), "render", str(ROOT / "systemd" / "network" / "travelpi-ap.network.in"), str(tmp / "out.network")],
    env=dict(os.environ, TRAVELPI_ULA_PREFIX_FILE=str(tmp / "ula-prefix")), capture_output=True, text=True)
check(rendered.returncode == 0, "template must render: " + rendered.stderr.strip())
NETWORK = (tmp / "out.network").read_text(encoding="utf-8") if rendered.returncode == 0 else ""
check("@ULA_" not in NETWORK and "fd7a:115c:a1e0" not in NETWORK,
      "rendered .network must have no placeholders and no Tailscale-range prefix")
check("@ULA_PREFIX@" in TEMPLATE and "@ULA_GATEWAY@" in TEMPLATE,
      "tracked travelpi-ap.network.in must stay generic (placeholders)")
check("IPv6SendRA=yes" in NETWORK,
      "travelpi-ap.network must send router advertisements")
check("Address=192.168.200.1/24 " + ULA_GATEWAY in NETWORK,
      "travelpi-ap.network must own the AP addresses (Address=) so networkd "
      "configures them instead of flushing the keeper's")
check(ULA_PREFIX in NETWORK,
      "travelpi-ap.network must advertise the configured ULA prefix " + ULA_PREFIX)
check("Autonomous=true" in NETWORK,
      "travelpi-ap.network must allow SLAAC on the ULA prefix")
check("Route=64:ff9b::/96" in NETWORK,
      "travelpi-ap.network must advertise the NAT64 route")
check("AcceptRA=no" in NETWORK,
      "travelpi-ap.network must not accept RAs on the AP interface")
check("travelpi-ula-init render /usr/local/share/travelpi/travelpi-ap.network.in /etc/systemd/network/070-travelpi-ap.network" in MAKEFILE,
      "deploy must render 070-travelpi-ap.network from the template with travelpi-ula-init")
check(MAKEFILE.find("/usr/local/libexec/travelpi-ula-init && ") < MAKEFILE.find("travelpi-ula-init render") and
      0 < MAKEFILE.find("/usr/local/libexec/travelpi-ula-init && "),
      "deploy must run travelpi-ula-init before rendering/enabling networkd")
check("ula-prefix" not in MAKEFILE.split("tailscale set", 1)[0].split("ts=\"\"")[-1],
      "deploy must not feed the ULA into tailscale; ADVERTISE_ROUTES is operator-set")
check("disable --now radvd.service" in MAKEFILE,
      "deploy must disable the broken radvd service")
check("enable --now systemd-networkd" in MAKEFILE,
      "deploy must enable systemd-networkd")

if failures:
    for failure in failures:
        print("FAIL: " + failure)
    sys.exit(1)
print("ap-address-guard: 0 failures (no hardcoded Tailscale ULA, keeper unit, "
      "systemd-networkd RA+address contract; keeper and helper behavior live in "
      "script-ap-keeper.py and radio-layout.py)")
