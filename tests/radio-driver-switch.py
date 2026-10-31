#!/usr/bin/env python3
"""Radio driver switch contract: the Wi-Fi 6E stick binds to mt7925u, with
a restore path to the proven mt7921u profile.

The stick reports the shared USB ID 0e8d:7961; mt7921u claimed it on this
host and hides the 6 GHz band (2026-10-30). Deploy installs a modprobe
blacklist for future boots and runs the live switch script. This guard
pins: the blacklist names both mt7921u modules, the switch script parses
as POSIX sh and contains the unbind/bind/verify/restore sequence, deploy
installs and runs both, and the helper journal matcher counts mt7925 flap
events alongside mt7921.
"""
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (ROOT / "systemd" / "travelpi-radio-driver").read_text(encoding="utf-8")
BLACKLIST = (ROOT / "systemd" / "modprobe" / "travelpi-mt7925.conf").read_text(encoding="utf-8")
MAKE = (ROOT / "Makefile").read_text(encoding="utf-8")
HELPER = (ROOT / "helper" / "travelpi-cockpit").read_text(encoding="utf-8")
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


# --- blacklist -----------------------------------------------------------
check("blacklist mt7921u" in BLACKLIST, "modprobe drop-in must blacklist mt7921u")
check("blacklist mt7921_common" in BLACKLIST, "modprobe drop-in must blacklist mt7921_common")

# --- switch script --------------------------------------------------------
sh = subprocess.run(["sh", "-n", str(ROOT / "systemd" / "travelpi-radio-driver")],
                    capture_output=True, text=True)
check(sh.returncode == 0, "switch script must parse as POSIX sh: " + sh.stderr.strip())
check("mt7925u" in SCRIPT, "switch script must name mt7925u")
check("$SYS/bus/usb/drivers/mt7921u/unbind" in SCRIPT,
      "switch script must unbind the interface from mt7921u")
check("$SYS/bus/usb/drivers/mt7925u/bind" in SCRIPT,
      "switch script must bind via the mt7925u interface-driver directory")
check("$SYS/bus/usb/drivers/mt7921u/bind" in SCRIPT,
      "switch restore path must bind via the mt7921u interface-driver directory")
check("bus/usb/drivers/usb/bind" not in SCRIPT,
      "switch script must not write the interface dir to drivers/usb/bind (device-dir only; the 2026-10-30 hangbug)")
check("-F alias mt7925u" in SCRIPT,
      "switch script must gate on the mt7925u alias table covering the device's USB id")
check("idProduct" in SCRIPT, "switch script must read the device USB product id for the gate")
check("modprobe mt7925u" in SCRIPT, "switch script must load mt7925u before the switch")
check("modprobe -r mt7921u" in SCRIPT, "switch script must remove mt7921u before rebinding")
check('while [ "$tries" -lt 30 ]' in SCRIPT,
      "switch script must poll for the MT7925 phy instead of a fixed sleep")
check(SCRIPT.count("svc try-restart radvd") >= 2,
      "switch script must try-restart radvd on the success and restore paths")
check("systemctl restart radvd" not in SCRIPT and "svc restart radvd" not in SCRIPT,
      "switch script must not start a disabled radvd (networkd owns RAs, ADR 0006)")
check("rm -f \"$BLACKLIST\"" in SCRIPT, "switch restore path must remove the blacklist")
check("modprobe mt7921u" in SCRIPT, "switch restore path must re-probe mt7921u")
check(SCRIPT.count("svc restart hostapd") >= 2,
      "switch script must restart hostapd on both the success and restore paths")

# --- deploy wiring --------------------------------------------------------
check("systemd/modprobe/travelpi-mt7925.conf /etc/modprobe.d/travelpi-mt7925.conf" in MAKE,
      "deploy must install the mt7925 modprobe drop-in")
check("systemd/travelpi-radio-driver /usr/local/libexec/travelpi-radio-driver" in MAKE,
      "deploy must install the radio driver switch script")
check("sudo /usr/local/libexec/travelpi-radio-driver" in MAKE,
      "deploy must run the radio driver switch")

# --- boot unit ------------------------------------------------------------
UNIT = (ROOT / "systemd" / "travelpi-radio-driver.service").read_text(encoding="utf-8")
check("Before=hostapd.service" in UNIT, "boot unit must run before hostapd")
check("After=systemd-modules-load.service" in UNIT, "boot unit must run after modules are loaded")
check("Type=oneshot" in UNIT and "RemainAfterExit=yes" in UNIT, "boot unit must be a RemainAfterExit oneshot")
check("ExecStart=/usr/local/libexec/travelpi-radio-driver" in UNIT, "boot unit must run the gate")
check("TRAVELPI_RADIO_BOOT=1" in UNIT, "boot unit must tell the gate not to touch services that have not started")

# --- behavior: run the real script against a fake sysfs with shims -----------
def run_gate(*, netdev, driver, alias, boot=False, blacklist=True):
    """Build a fake sysfs and shims, run the gate, return (root, proc)."""
    root = Path(tempfile.mkdtemp(prefix="travelpi-radio-gate-"))
    sysroot = root / "sys"
    dev = sysroot / "devices" / "platform" / "usb1" / "1-1" / "1-1.2"
    iface = dev / "1-1.2:1.0"
    iface.mkdir(parents=True)
    (dev / "idVendor").write_text("0e8d\n")
    (dev / "idProduct").write_text("7961\n")
    (sysroot / "bus" / "usb" / "devices").mkdir(parents=True)
    (sysroot / "bus" / "usb" / "devices" / "1-1.2").symlink_to(dev)
    (sysroot / "bus" / "usb" / "devices" / "1-1.2:1.0").symlink_to(iface)
    for name in ("mt7921u", "mt7925u"):
        (sysroot / "bus" / "usb" / "drivers" / name).mkdir(parents=True)
    if driver:
        (iface / "driver").symlink_to(sysroot / "bus" / "usb" / "drivers" / driver)
    if netdev:
        (sysroot / "class" / "net" / "wlan1").mkdir(parents=True)
        (sysroot / "class" / "net" / "wlan1" / "device").symlink_to(iface)
        (sysroot / "class" / "ieee80211" / "phy0").mkdir(parents=True)
        (sysroot / "class" / "ieee80211" / "phy0" / "device").symlink_to(iface)
    (root / "bin").mkdir()
    for tool in ("modprobe", "systemctl", "logger"):
        shim = root / "bin" / tool
        shim.write_text('#!/bin/sh\necho "%s $*" >> "$SHIM_LOG"\nexit 0\n' % tool)
        shim.chmod(0o755)
    modinfo = root / "modinfo"
    modinfo.write_text("#!/bin/sh\n" + ("echo 'usb:v0E8Dp%s*'\n" % alias if alias else "exit 0\n"))
    modinfo.chmod(0o755)
    conf = root / "travelpi-mt7925.conf"
    if blacklist:
        conf.write_text("blacklist mt7921u\n")
    env = dict(os.environ, PATH=str(root / "bin") + os.pathsep + os.environ["PATH"],
               SHIM_LOG=str(root / "shim.log"), TRAVELPI_SYS_ROOT=str(sysroot),
               TRAVELPI_BLACKLIST=str(conf), TRAVELPI_MODINFO=str(modinfo),
               TRAVELPI_RADIO_BOOT="1" if boot else "0", TRAVELPI_RADIO_WAIT="0")
    proc = subprocess.run(["/bin/sh", str(ROOT / "systemd" / "travelpi-radio-driver")],
                          env=env, capture_output=True, text=True, timeout=60)
    return root, proc


def shim_log(root):
    log = root / "shim.log"
    return log.read_text() if log.exists() else ""


def bound(root, driver):
    f = root / "sys" / "bus" / "usb" / "drivers" / driver / "bind"
    return f.read_text().strip() if f.exists() else None


# Driverless stick, no netdev, kernel mt7925u does NOT claim 7961: the
# blacklist goes away and mt7921u is rebound (the 2026-10-30 outage).
root, proc = run_gate(netdev=False, driver=None, alias="7925")
check(proc.returncode == 0, "driverless gate must exit 0: " + proc.stderr)
check(not (root / "travelpi-mt7925.conf").exists(), "driverless + unsupported must remove the blacklist")
check(bound(root, "mt7921u") == "1-1.2:1.0", "driverless + unsupported must rebind mt7921u")
check("modprobe mt7921u" in shim_log(root), "driverless + unsupported must load mt7921u")
shutil.rmtree(root)

# Driverless stick on a kernel whose mt7925u claims 7961: bind mt7925u, keep the blacklist.
root, proc = run_gate(netdev=False, driver=None, alias="7961")
check(bound(root, "mt7925u") == "1-1.2:1.0", "driverless + supported must bind mt7925u")
check((root / "travelpi-mt7925.conf").exists(), "driverless + supported keeps the blacklist")
shutil.rmtree(root)

# Netdev present but no driver on the phy (the `*)` branch): same repair.
root, proc = run_gate(netdev=True, driver=None, alias="7925")
check(not (root / "travelpi-mt7925.conf").exists(), "no-driver phy must remove the blacklist")
check(bound(root, "mt7921u") == "1-1.2:1.0", "no-driver phy must rebind a driver")
shutil.rmtree(root)

# mt7921u bound, mt7925u cannot claim the id: blacklist removed, nothing unbound.
root, proc = run_gate(netdev=True, driver="mt7921u", alias="7925")
check(not (root / "travelpi-mt7925.conf").exists(), "unsupported kernel must drop the blacklist")
check(bound(root, "mt7921u") is None, "a working mt7921u must not be unbound")
shutil.rmtree(root)

# Already on mt7925u: nothing happens.
root, proc = run_gate(netdev=True, driver="mt7925u", alias="7961")
check(proc.returncode == 0 and (root / "travelpi-mt7925.conf").exists(), "mt7925u in place is left alone")
check("systemctl" not in shim_log(root), "an already-correct radio must not restart services")
shutil.rmtree(root)

# Boot mode never calls systemctl (hostapd has not started; no self-deadlock before it).
root, proc = run_gate(netdev=False, driver=None, alias="7925", boot=True)
check("systemctl" not in shim_log(root), "boot mode must not call systemctl: " + shim_log(root))
check(not (root / "travelpi-mt7925.conf").exists(), "boot mode still repairs the driver")
shutil.rmtree(root)
# Live (deploy-time) repair restarts the AP services.
root, proc = run_gate(netdev=False, driver=None, alias="7925", boot=False)
check("systemctl restart hostapd" in shim_log(root), "live repair must restart hostapd")
shutil.rmtree(root)

# --- helper journal matcher -----------------------------------------------
check(re.search(r"'mt7921' in low or 'mt7925' in low", HELPER) is not None,
      "helper journal matcher must count mt7925 flap events")

if failures:
    for failure in failures:
        print("FAIL: " + failure)
    sys.exit(1)
print("radio-driver-switch: guard passed "
      "(blacklist, bind/verify/restore sequence, deploy wiring, journal matcher)")
