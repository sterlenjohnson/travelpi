#!/usr/bin/env python3
"""Service hardening contract (ADR 0008).

Parses every TravelPi unit under systemd/ and asserts the baseline directives,
the per-unit extras chosen in the ADR, and the safety rules that keep the
hardening from breaking the router:

* no unit combines PrivateNetwork=yes with a script that needs the network;
* a unit whose script writes outside /run and /var/lib never gets
  ProtectSystem=strict (only `full`, or nothing when it writes /etc);
* every unit with Restart= carries StartLimit*, every unit has a MemoryMax.

The TABLE below is the executable form of the ADR; edit both together.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYSTEMD = ROOT / "systemd"
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


def parse(path):
    """Return {section: {key: [values]}} ignoring comments and blank lines."""
    out, sec = {}, None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        m = re.fullmatch(r"\[(\w+)\]", line)
        if m:
            sec = out.setdefault(m.group(1), {})
            continue
        if "=" in line and sec is not None:
            k, v = line.split("=", 1)
            sec.setdefault(k.strip(), []).append(v.strip())
    return out


# unit -> (writes_outside_run_var_lib, needs_network, strict_ok, extras)
#   writes_outside: the script writes under /etc, /usr or /boot (blocks any
#                   ProtectSystem value, strict in particular).
#   needs_network:  the script opens sockets / uses ip, tc, curl, nmcli
#                   (forbids PrivateNetwork=yes).
#   extras:         {(section, key): exact value} required in addition to the
#                   baseline.
BASE_SERVICE = {
    "NoNewPrivileges": "yes",
    "ProtectHome": "yes",
    "RestrictRealtime": "yes",
    "LockPersonality": "yes",
    "PrivateTmp": "yes",  # no unit exchanges files through /tmp (state: /run, /var/lib)
}
TABLE = {
    # curl + `date -u -s` on an untrusted header: strongest profile.
    "travelpi-clockset.service": (False, True, True, {
        "CapabilityBoundingSet": "CAP_SYS_TIME",
        "RestrictAddressFamilies": "AF_INET AF_INET6 AF_UNIX",
        "ProtectSystem": "strict", "PrivateDevices": "yes",
        "ProtectKernelModules": "yes", "ProtectControlGroups": "yes",
        "TimeoutStartSec": "30", "MemoryMax": "64M"}),
    # tar of /etc, /opt, /var/lib/tailscale into /var/lib/travelpi/backups.
    "travelpi-config-backup.service": (False, False, False, {
        "ProtectSystem": "full", "TimeoutStartSec": "300", "MemoryMax": "128M"}),
    # writes /var/lib/travelpi + /run, kills any pid, calls systemctl.
    "travelpi-mem-watch.service": (False, False, False, {
        "ProtectSystem": "full", "MemoryMax": "64M"}),
    # echo into /sys/devices/system/cpu only; no network.
    "travelpi-power-profile.service": (False, False, True, {
        "ProtectSystem": "strict", "ReadWritePaths": "/sys/devices/system/cpu",
        "PrivateNetwork": "yes", "TimeoutStartSec": "30", "MemoryMax": "64M"}),
    # vcgencmd (/dev/vcio) + /var/lib/travelpi.
    "travelpi-power-record.service": (False, False, False, {
        "ProtectSystem": "full", "TimeoutStartSec": "30", "TimeoutStopSec": "30",
        "MemoryMax": "64M"}),
    # modprobe, rm /etc/modprobe.d blacklist, /sys bind, systemctl: no ProtectSystem.
    "travelpi-radio-driver.service": (True, True, False, {
        "TimeoutStartSec": "180", "MemoryMax": "64M"}),
    # ip link, /sys USB unbind, systemctl restart hostapd, /run + /var/lib.
    "travelpi-radio-watch.service": (False, True, False, {
        "ProtectSystem": "full", "MemoryMax": "64M"}),
    # curl --interface wlan0, rewrites /etc/default/travelpi-sqm: no ProtectSystem.
    "travelpi-sqm-tune.service": (True, True, False, {
        "TimeoutStartSec": "180", "MemoryMax": "64M"}),
    # modprobe + ip + tc: netlink, no disk writes.
    "travelpi-sqm.service": (False, True, False, {
        "ProtectSystem": "full", "TimeoutStartSec": "60", "TimeoutStopSec": "60",
        "MemoryMax": "64M"}),
    # ip, sysctl -w /proc/sys, nmcli, systemctl: no disk writes.
    "wlan1-static-ip.service": (False, True, False, {
        "ProtectSystem": "full", "MemoryMax": "64M"}),
}
# Directives that would break a script that touches these; asserted absent.
FORBIDDEN = {
    "travelpi-mem-watch.service": ["ProtectProc", "PrivateUsers", "CapabilityBoundingSet",
                                   "RestrictAddressFamilies", "PrivateNetwork"],
    "travelpi-radio-driver.service": ["ProtectKernelModules", "ProtectKernelTunables",
                                      "PrivateDevices", "PrivateNetwork"],
    "travelpi-radio-watch.service": ["ProtectKernelTunables", "PrivateDevices",
                                     "PrivateNetwork", "RestrictAddressFamilies"],
    "travelpi-power-record.service": ["PrivateDevices"],  # vcgencmd needs /dev/vcio
    "travelpi-sqm.service": ["ProtectKernelModules", "PrivateNetwork",
                             "RestrictAddressFamilies", "PrivateDevices"],
    "travelpi-sqm-tune.service": ["PrivateNetwork", "RestrictAddressFamilies"],
    "wlan1-static-ip.service": ["ProtectKernelTunables", "PrivateNetwork",
                                "RestrictAddressFamilies"],
    "travelpi-clockset.service": ["ProtectClock"],  # would block date -u -s
}

units = sorted(p.name for p in SYSTEMD.glob("*.service")) + sorted(p.name for p in SYSTEMD.glob("*.timer"))
services = [u for u in units if u.endswith(".service")]
check(sorted(services) == sorted(TABLE), "every systemd/*.service must have a TABLE entry: %s vs %s"
      % (services, sorted(TABLE)))

for name, (writes_outside, needs_net, strict_ok, extras) in TABLE.items():
    path = SYSTEMD / name
    if not path.exists():
        check(False, "%s missing" % name)
        continue
    unit = parse(path)
    svc, uni = unit.get("Service", {}), unit.get("Unit", {})

    def val(key):
        v = svc.get(key)
        return v[-1] if v else None

    for k, want in BASE_SERVICE.items():
        check(val(k) == want, "%s: [Service] %s=%s required" % (name, k, want))
    for k, want in extras.items():
        check(val(k) == want, "%s: [Service] %s=%s required (got %s)" % (name, k, want, val(k)))
    mm = val("MemoryMax")
    check(mm is not None and re.fullmatch(r"\d+M", mm), "%s: MemoryMax must be a bounded megabyte value" % name)
    if val("Type") == "oneshot" and name in (
            "travelpi-clockset.service", "travelpi-config-backup.service", "travelpi-sqm-tune.service"):
        check(val("TimeoutStartSec") is not None, "%s: hang-prone oneshot needs TimeoutStartSec" % name)
    if "Restart" in svc:
        check(uni.get("StartLimitIntervalSec") == ["300"], "%s: StartLimitIntervalSec=300 required" % name)
        check(uni.get("StartLimitBurst") == ["5"], "%s: StartLimitBurst=5 required" % name)
    else:
        check("StartLimitBurst" not in uni, "%s: StartLimit* only matters with Restart=" % name)
    for k in FORBIDDEN.get(name, []):
        check(k not in svc, "%s: %s would break the script (see ADR 0008)" % (name, k))
    # PrivateNetwork=yes only for scripts that need no network.
    if val("PrivateNetwork") == "yes":
        check(not needs_net, "%s: PrivateNetwork=yes but the script needs the network" % name)
    # Scripts that write /etc, /usr or /boot cannot be under any ProtectSystem;
    # strict additionally requires an explicit audited write set.
    ps = val("ProtectSystem")
    if writes_outside:
        check(ps is None, "%s: script writes outside /run,/var/lib so ProtectSystem must be unset" % name)
    if ps == "strict":
        check(strict_ok, "%s: ProtectSystem=strict is not audited for this script" % name)
        check(not writes_outside, "%s: strict with writes outside /run,/var/lib" % name)
    # Only the ReadWritePaths named above may relax strict.
    if "ReadWritePaths" in svc:
        check(ps == "strict" and svc["ReadWritePaths"] == [extras.get("ReadWritePaths")],
              "%s: unexpected ReadWritePaths" % name)
    # Every directive in the file must be justified next to it.
    text = path.read_text(encoding="utf-8")
    check("# hardening:" in text, "%s: missing '# hardening:' justification comments" % name)
    for k in list(BASE_SERVICE) + [k for k in extras if k not in ("TimeoutStartSec", "TimeoutStopSec")]:
        m = re.search(r"^%s=" % k, text, re.M)
        if m:
            before = text[:m.start()].rstrip().splitlines()
            # a '# hardening:' comment must sit in the comment block above this
            # directive, or in the contiguous block of directives it shares one with
            idx = len(before) - 1
            found = False
            while idx >= 0 and (before[idx].startswith("#") or "=" in before[idx]):
                if before[idx].startswith("# hardening:"):
                    found = True
                    break
                idx -= 1
            check(found, "%s: %s has no '# hardening:' comment above it" % (name, k))

# The AP keeper must not be tied to hostapd's lifecycle (ADR 0008).
keeper = parse(SYSTEMD / "wlan1-static-ip.service")
check("PartOf" not in keeper.get("Unit", {}), "wlan1-static-ip.service must not use PartOf=")
check("BindsTo" not in parse(SYSTEMD / "travelpi-radio-watch.service").get("Unit", {}),
      "travelpi-radio-watch.service must not BindsTo= hostapd (it restarts hostapd)")

# Timers only schedule; they carry no sandbox, but must keep their own services.
for t in (SYSTEMD).glob("*.timer"):
    check((SYSTEMD / (t.stem + ".service")).exists(), "%s has no matching service" % t.name)

# ADR and README mention.
adr = ROOT / "docs/adr/0008-service-hardening.md"
check(adr.exists() and "Accepted" in adr.read_text(encoding="utf-8"), "ADR 0008 must exist and be Accepted")
check("0008" in (ROOT / "README.md").read_text(encoding="utf-8") or
      "service hardening" in (ROOT / "README.md").read_text(encoding="utf-8").lower(),
      "README must mention service hardening")

if failures:
    print("unit-hardening FAILED:")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("unit-hardening ok (%d units)" % len(TABLE))
