#!/usr/bin/env python3
"""Per-install ULA contract: systemd/travelpi-ula-init owns /etc/travelpi/ula-prefix.

Runs the POSIX sh generator in a temp dir (TRAVELPI_ULA_PREFIX_FILE,
TRAVELPI_NETWORK_FILE, TRAVELPI_RANDOM_SOURCE overrides) and checks: random
RFC 4193 generation, idempotence, never overwriting, junk refusal, migration of
a live prefix, template rendering, and the helper reading the same file.
"""
import importlib.machinery
import importlib.util
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = str(ROOT / "systemd" / "travelpi-ula-init")
VALID = re.compile(r"^fd[0-9a-f]{2}:[0-9a-f]{1,4}:[0-9a-f]{1,4}:[0-9a-f]{1,4}::/64$")
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


tmp = Path(tempfile.mkdtemp(prefix="travelpi-ula-"))
prefix_file = tmp / "etc" / "travelpi" / "ula-prefix"
network_file = tmp / "070.network"
rand = tmp / "random"
rand.write_bytes(bytes.fromhex("12345678ab"))
ENV = dict(os.environ, TRAVELPI_ULA_PREFIX_FILE=str(prefix_file),
           TRAVELPI_NETWORK_FILE=str(network_file), TRAVELPI_RANDOM_SOURCE=str(rand))


def run(*args, env=None):
    return subprocess.run(["sh", INIT, *args], env=env or ENV, capture_output=True, text=True)


check(subprocess.run(["sh", "-n", INIT]).returncode == 0, "generator must parse as POSIX sh")

# 1. Generation from fixed random bytes: fd + 40 bits, subnet id 1.
r = run()
check(r.returncode == 0, "generation failed: " + r.stderr)
check(prefix_file.read_text() == "fd12:3456:78ab:1::/64\n", "unexpected generated prefix: " + prefix_file.read_text())
check(VALID.match(prefix_file.read_text().strip()) is not None, "generated prefix must be a valid ULA /64")

# 2. Idempotent and never overwrites, even when the random source changes.
rand.write_bytes(bytes.fromhex("ffffffffff"))
before = prefix_file.read_text()
r = run()
check(r.returncode == 0 and r.stdout.strip() == before.strip() and prefix_file.read_text() == before,
      "existing file must be kept and printed unchanged")

# 3. Real /dev/urandom yields a valid prefix.
fresh = tmp / "fresh"
r = run(env=dict(ENV, TRAVELPI_ULA_PREFIX_FILE=str(fresh), TRAVELPI_RANDOM_SOURCE="/dev/urandom"))
check(r.returncode == 0 and VALID.match(fresh.read_text().strip()) is not None,
      "urandom generation must produce a valid prefix: " + r.stderr)

# 4. Junk is refused and left untouched.
junk = tmp / "junk"
for bad in ["hello", "2001:db8::/64", "fd12:3456:789a:1::/48", "FD12:3456:789a:1::/64", ""]:
    junk.write_text(bad + "\n")
    r = run(env=dict(ENV, TRAVELPI_ULA_PREFIX_FILE=str(junk)))
    check(r.returncode != 0 and junk.read_text() == bad + "\n", "junk %r must be refused unchanged" % bad)

# 5. Migration: an installed profile's live prefix is adopted, not regenerated.
mig = tmp / "migrated"
network_file.write_text("[Network]\nAddress=192.168.200.1/24 fd00:db8:1:200::1/64\n[IPv6Prefix]\nPrefix=fd0a:bcde:f012:200::/64\nOnLink=true\n")
r = run(env=dict(ENV, TRAVELPI_ULA_PREFIX_FILE=str(mig)))
check(r.returncode == 0 and mig.read_text() == "fd0a:bcde:f012:200::/64\n", "live prefix must be migrated: " + r.stderr + mig.read_text())
# A network file with no/invalid prefix falls back to generation.
network_file.write_text("[IPv6Prefix]\nPrefix=2001:db8::/64\n")
gen = tmp / "gen"
r = run(env=dict(ENV, TRAVELPI_ULA_PREFIX_FILE=str(gen)))
check(r.returncode == 0 and gen.read_text() == "fdff:ffff:ffff:1::/64\n", "non-ULA network prefix must not be migrated")

# 6. Rendering: the tracked template becomes a profile with the configured prefix.
out = tmp / "out.network"
r = run("render", str(ROOT / "systemd" / "network" / "travelpi-ap.network.in"), str(out))
text = out.read_text() if out.exists() else ""
check(r.returncode == 0, "render failed: " + r.stderr)
check("Address=192.168.200.1/24 fd12:3456:78ab:1::1/64" in text, "rendered Address= must carry the gateway")
check("Prefix=fd12:3456:78ab:1::/64" in text and "IPv6Prefix=fd12:3456:78ab:1::/64" in text, "rendered Prefix must be the configured one")
check("Route=64:ff9b::/96" in text and "IPv6SendRA=yes" in text and "AcceptRA=no" in text, "RA semantics must be kept")
check("@ULA" not in text and "fd7a:115c:a1e0" not in text, "no placeholders and no Tailscale-range prefix in output")
radvd = tmp / "radvd.conf"
r = run("render", str(ROOT / "systemd" / "travelpi-radvd.conf"), str(radvd))
check(r.returncode == 0 and "prefix fd12:3456:78ab:1::/64" in radvd.read_text(), "radvd template must render")
missing = run("render", str(ROOT / "systemd" / "travelpi-radvd.conf"), str(tmp / "x"),
              env=dict(ENV, TRAVELPI_ULA_PREFIX_FILE=str(tmp / "absent")))
check(missing.returncode != 0, "render without a prefix file must fail")

# 7. The helper reads the same file; absent or junk means None (no hardcoded fallback).
loader = importlib.machinery.SourceFileLoader("travelpi_helper", str(ROOT / "helper" / "travelpi-cockpit"))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)
helper.ULA_PREFIX_FILE = str(prefix_file)
check(helper.ula_prefix() == "fd12:3456:78ab:1::/64" and helper.ap_v6_gateway() == "fd12:3456:78ab:1::1/64",
      "helper must read the configured prefix")
helper.ULA_PREFIX_FILE = str(tmp / "absent")
check(helper.ula_prefix() is None and helper.ap_v6_gateway() is None, "absent file means no ULA configured")
helper.ULA_PREFIX_FILE = str(junk)
check(helper.ula_prefix() is None, "junk file means no ULA configured")

# 8. Deploy wiring.
make = (ROOT / "Makefile").read_text()
check("systemd/travelpi-ula-init /usr/local/libexec/travelpi-ula-init" in make, "deploy must install the generator")
check("systemd/network/travelpi-ap.network.in /usr/local/share/travelpi/travelpi-ap.network.in" in make, "deploy must install the template")
check("/usr/local/libexec/travelpi-ula-init && " in make, "deploy must run the generator")
check("tailscale set --advertise-routes" not in make or "ADVERTISE_ROUTES" in make, "advertising stays operator opt-in")
_backup_text = (ROOT / "systemd" / "travelpi-config-backup").read_text()
_listed = _backup_text.split("# BEGIN BACKUP PATHS", 1)[-1].split("# END BACKUP PATHS", 1)[0].split()
check("etc/travelpi" in _listed, "backup must include /etc/travelpi (the ula-prefix file and its siblings)")

if failures:
    for f in failures:
        print("FAIL: " + f)
    sys.exit(1)
print("ula-prefix: generation, idempotence, junk refusal, migration, render, helper and deploy wiring checks passed")
