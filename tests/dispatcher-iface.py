#!/usr/bin/env python3
"""The AdGuard hotel-DNS dispatcher acts on the WAN interface, and on eth0 only
while eth0 holds the default route. Run for real with PATH shims."""
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "systemd" / "travelpi-adguard-hotel-dns"
failures = []


def run(iface, eth0_default):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        for name, body in {
            "ip": 'if [ "$*" = "route show default dev eth0" ]; then ' + ('echo "default via 10.0.0.1 dev eth0"' if eth0_default else ":") + "; fi\n",
            "tailscale": "exit 0\n",
            "systemctl": 'echo restart >> "$MARK"\n',
            "logger": "exit 0\n",
        }.items():
            (bin_dir / name).write_text("#!/bin/sh\n" + body)
            (bin_dir / name).chmod(0o755)
        cfg = tmp / "AdGuardHome.yaml"
        cfg.write_text("dns:\n  upstream_dns:\n    - 9.9.9.9\n  fallback_dns: []\n  upstream_dns_file: \"\"\n")
        mark = tmp / "mark"
        env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ["PATH"], ADGUARD_YAML=str(cfg),
                   DHCP4_NAMESERVERS="172.20.0.1", MARK=str(mark))
        proc = subprocess.run(["/bin/sh", str(SCRIPT), iface, "dhcp4-change"], env=env, capture_output=True, text=True)
        return proc.returncode, "172.20.0.1" in cfg.read_text()


def check(cond, label):
    if not cond:
        failures.append(label)


check(run("wlan0", False) == (0, True), "wlan0 must rewrite upstreams")
check(run("eth0", True) == (0, True), "eth0 holding the default route must rewrite upstreams")
check(run("eth0", False) == (0, False), "eth0 without the default route must be ignored")
check(run("wlan1", True) == (0, False), "other interfaces must be ignored")

if failures:
    print("dispatcher iface FAILED:")
    for item in failures:
        print("  - " + item)
    sys.exit(1)
print("dispatcher iface checks passed")
