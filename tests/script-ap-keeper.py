#!/usr/bin/env python3
"""systemd/travelpi-ap-ip (the AP address keeper) run under PATH shims.

The shims keep a tiny stateful model of the AP interface (IPv4 address, ULA
gateway, link-local) so the keeper's own checks see the results of its
actions. Pinned, as behavior rather than source text:

- the keeper never flushes IPv6 and never runs a family-blind `addr flush`
  (the 2026-10-30 ULA incident: a flush wiped the link-local address and every
  router advertisement became invalid);
- the keeper never restarts systemd-networkd (the 2026-10-30 15 s oscillation:
  networkd restarts flush the addresses networkd itself owns), and in watch
  mode a healthy interface causes no mutation on later ticks;
- missing pieces are repaired in the right order (link-local toggle before the
  gateway add), the ULA gateway is derived from the configured prefix, and
  with no prefix configured the keeper manages IPv4 only.
"""
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import subprocess
import sys
import tempfile
from pathlib import Path
import atexit
import shutil


def _mkdtemp(prefix):
    """Temp dir removed at interpreter exit, even on failure."""
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, True)
    return path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'systemd' / 'travelpi-ap-ip'
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


PREFIX = 'fd12:3456:789a:1::/64'     # generic per-install example
GATEWAY = 'fd12:3456:789a:1::1/64'

SHIMS = {
    # stateful model: files v4 / v6 / ll in $SHIM_DIR mean the address exists
    'ip': r'''echo "ip $*" >> "$SHIM_LOG"
case "$*" in
  "-4 addr show dev "*) [ -e "$SHIM_DIR/v4" ] && echo "    inet 192.168.200.1/24 scope global wlan1";;
  "-6 addr show dev "*"scope global") [ -e "$SHIM_DIR/v6" ] && echo "    inet6 fd12:3456:789a:1::1/64 scope global";;
  "-6 addr show dev "*"scope link") [ -e "$SHIM_DIR/ll" ] && echo "    inet6 fe80::1/64 scope link";;
  "-4 addr flush dev "*) rm -f "$SHIM_DIR/v4";;
  "addr add 192.168.200.1/24 dev "*) : > "$SHIM_DIR/v4";;
  "-6 addr add "*) : > "$SHIM_DIR/v6";;
  *"addr flush"*) rm -f "$SHIM_DIR/v4" "$SHIM_DIR/v6" "$SHIM_DIR/ll";;
esac
exit 0
''',
    # disable_ipv6=1 wipes v6 (globals and link-local); =0 regenerates link-local
    'sysctl': r'''echo "sysctl $*" >> "$SHIM_LOG"
case "$*" in
  *disable_ipv6=1) rm -f "$SHIM_DIR/v6" "$SHIM_DIR/ll";;
  *disable_ipv6=0) : > "$SHIM_DIR/ll";;
esac
exit 0
''',
    'systemctl': 'echo "systemctl $*" >> "$SHIM_LOG"\n',
    'nmcli': 'echo "nmcli $*" >> "$SHIM_LOG"\n',
    'logger': 'echo "logger $*" >> "$SHIM_LOG"\n',
    'sleep': ('if [ -e "$SHIM_DIR/flap" ]; then rm -f "$SHIM_DIR/flap" "$SHIM_DIR/v4" "$SHIM_DIR/v6" "$SHIM_DIR/ll"; fi\n'
              'n=$(cat "$SHIM_DIR/loops" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_DIR/loops"\n'
              'if [ "$n" -ge "${MAX_LOOPS:-1}" ]; then kill -TERM "$PPID"; fi\n'),
}


def run_keeper(v4=False, v6=False, ll=False, ula=True, ula_text=None, flap_after_first_tick=False, iface_present=True, watch_ticks=0, hostapd_iface='wlan1'):
    root = Path(_mkdtemp(prefix='travelpi-ap-keeper-'))
    shims = root / 'bin'
    shims.mkdir()
    for name, body in SHIMS.items():
        shim = shims / name
        shim.write_text('#!/bin/sh\n' + body)
        shim.chmod(0o755)
    for flag, on in (('v4', v4), ('v6', v6), ('ll', ll)):
        if on:
            (root / flag).write_text('')
    sysroot = root / 'sys'
    (sysroot / 'class' / 'net').mkdir(parents=True)
    if iface_present:
        (sysroot / 'class' / 'net' / 'wlan1').mkdir()
    (root / 'hostapd.conf').write_text('driver=nl80211\ninterface=%s\nssid=TravelPi\n' % hostapd_iface)
    if ula:
        (root / 'ula-prefix').write_text((ula_text if ula_text is not None else PREFIX) + '\n')
    if flap_after_first_tick:
        (root / 'flap').write_text('')
    env = dict(os.environ, PATH=str(shims) + os.pathsep + os.environ['PATH'], SHIM_LOG=str(root / 'shim.log'),
               SHIM_DIR=str(root), TRAVELPI_IP=str(shims / 'ip'), TRAVELPI_SYSTEMCTL=str(shims / 'systemctl'),
               TRAVELPI_NMCLI=str(shims / 'nmcli'), TRAVELPI_HOSTAPD_CONF=str(root / 'hostapd.conf'),
               TRAVELPI_SYS_ROOT=str(sysroot), TRAVELPI_ULA_PREFIX_FILE=str(root / 'ula-prefix'))
    args = ['/bin/sh', str(SCRIPT)]
    if watch_ticks:
        env['MAX_LOOPS'] = str(watch_ticks)
        args.append('watch')
    proc = subprocess.run(args, env=env, capture_output=True, text=True, timeout=60)
    return root, proc


def calls(root):
    log = root / 'shim.log'
    return log.read_text().splitlines() if log.exists() else []


def mutations(root):
    return [c for c in calls(root) if c.startswith(('ip link', 'ip addr', 'ip -4 addr add', 'ip -4 addr flush', 'ip -6 addr add',
                                                      'ip -6 addr flush', 'sysctl', 'systemctl'))]


def invariants(root, label):
    lines = calls(root)
    check(not any('flush' in c and not c.startswith('ip -4 addr flush') for c in lines),
          label + ': the keeper must never flush IPv6 or run a family-blind flush: %s' % lines)
    check(not any(c.startswith('systemctl') and 'networkd' in c for c in lines),
          label + ': the keeper must never restart systemd-networkd: %s' % lines)
    check(not any(c.startswith('systemctl') and not c.startswith('systemctl try-restart radvd') for c in lines),
          label + ': the only service the keeper may touch is a legacy radvd try-restart: %s' % lines)


# --- everything missing (USB flap re-created the interface): repaired in order.
root, proc = run_keeper()
lines = calls(root)
invariants(root, 'flap')
check(proc.returncode == 0, 'one-shot apply must exit 0: ' + proc.stderr)
check('ip link set wlan1 up' in lines and 'ip -4 addr flush dev wlan1' in lines and 'ip addr add 192.168.200.1/24 dev wlan1' in lines,
      'the IPv4 address must be (re)applied with an IPv4-scoped flush: %s' % lines)
check('ip -6 addr add %s dev wlan1' % GATEWAY in lines, 'the ULA gateway must be derived from the prefix file: %s' % lines)
check('sysctl -qw net.ipv6.conf.wlan1.disable_ipv6=1' in lines and 'sysctl -qw net.ipv6.conf.wlan1.disable_ipv6=0' in lines,
      'a missing link-local must be recovered with the disable_ipv6 toggle: %s' % lines)
toggle_off = lines.index('sysctl -qw net.ipv6.conf.wlan1.disable_ipv6=0')
check(toggle_off < lines.index('ip -6 addr add %s dev wlan1' % GATEWAY),
      'the link-local toggle must run before the gateway add (the toggle wipes v6 globals): %s' % lines)
check(lines.index('nmcli device set wlan1 managed no') < lines.index('ip link set wlan1 up'),
      'the AP radio must be handed away from NetworkManager first')
check(any(c.startswith('logger') and 'AP addresses applied to wlan1' in c for c in lines), 'the repair must be logged')
check((root / 'v4').exists() and (root / 'v6').exists() and (root / 'll').exists(), 'the interface must end fully addressed')

# --- a healthy interface: no mutation at all.
root, proc = run_keeper(v4=True, v6=True, ll=True)
invariants(root, 'healthy')
check(mutations(root) == [], 'a healthy interface must not be touched: %s' % calls(root))
check(not any(c.startswith('logger') for c in calls(root)), 'a healthy interface logs nothing')

# --- only the IPv6 gateway is missing: no IPv4 flush, no v4 re-add (the v4 address must survive).
root, proc = run_keeper(v4=True, ll=True)
lines = calls(root)
invariants(root, 'v6 missing')
check('ip -6 addr add %s dev wlan1' % GATEWAY in lines, 'a missing gateway must be added: %s' % lines)
check(not any('flush' in c or c.startswith('ip addr add') for c in lines), 'a present IPv4 address must not be flushed or re-added: %s' % lines)
check(not any(c.startswith('sysctl') for c in lines), 'an existing link-local must not be toggled: %s' % lines)

# --- addresses present but link-local gone: toggle, then re-add the gateway the toggle removed.
root, proc = run_keeper(v4=True, v6=True, ll=False)
lines = calls(root)
invariants(root, 'link-local lost')
check('sysctl -qw net.ipv6.conf.wlan1.disable_ipv6=1' in lines, 'a lost link-local must be recovered by the toggle: %s' % lines)
check(lines.index('sysctl -qw net.ipv6.conf.wlan1.disable_ipv6=0') < lines.index('ip -6 addr add %s dev wlan1' % GATEWAY),
      'the gateway must be re-added after the toggle: %s' % lines)
check(not any('flush' in c for c in lines), 'recovering link-local must not flush anything: %s' % lines)
check((root / 'v6').exists() and (root / 'll').exists() and (root / 'v4').exists(), 'the IPv4 address must survive the link-local toggle')

# --- no ULA prefix configured: IPv4 only, nothing invented.
root, proc = run_keeper(ula=False)
lines = calls(root)
invariants(root, 'no prefix')
check('ip addr add 192.168.200.1/24 dev wlan1' in lines and not any(c.startswith('ip -6 addr add') for c in lines),
      'without a configured prefix the keeper must manage IPv4 only: %s' % lines)

# --- a malformed prefix file is treated as no prefix (and a non-/64 or non-ULA never becomes an address).
for bad in ('not-a-prefix', '2001:db8:1:1::/64', 'fd12:3456:789a:1::/48', ''):
    root, proc = run_keeper(ula_text=bad)
    check(not any(c.startswith('ip -6 addr add') for c in calls(root)) and 'ip addr add 192.168.200.1/24 dev wlan1' in calls(root),
          'prefix %r must be ignored, IPv4 still managed: %s' % (bad, calls(root)))
    invariants(root, 'bad prefix %r' % bad)

# --- the radio is absent (flap in progress) or hostapd names no interface: nothing happens.
root, proc = run_keeper(iface_present=False)
check(proc.returncode == 0 and mutations(root) == [], 'an absent interface must be left alone: %s' % calls(root))
root, proc = run_keeper(hostapd_iface='')
check(proc.returncode == 0 and mutations(root) == [], 'no interface in hostapd.conf must be left alone: %s' % calls(root))

# --- watch mode: the repair happens once; later ticks on a healthy interface mutate nothing
# (the oscillation signature was "AP addresses applied" every 15 s).
root, proc = run_keeper(watch_ticks=4)
lines = calls(root)
invariants(root, 'watch')
check(proc.returncode in (-15, 143), 'watch mode must keep looping until stopped: rc=%s %s' % (proc.returncode, proc.stderr))
check(len([c for c in lines if c.startswith('logger') and 'AP addresses applied' in c]) == 1,
      'a healthy interface must not be re-applied on later ticks: %s' % lines)
check(len([c for c in lines if c.startswith('ip addr add')]) == 1 and len([c for c in lines if 'flush' in c]) == 1,
      'addresses must be added and flushed once across ticks: %s' % lines)

# --- watch mode heals a later flap: addresses lost between ticks are repaired again, once per flap.
root, proc = run_keeper(watch_ticks=4, flap_after_first_tick=True)
lines = calls(root)
invariants(root, 'watch flap')
check(len([c for c in lines if c.startswith('logger') and 'AP addresses applied' in c]) == 2,
      'one repair per flap, none on healthy ticks: %s' % lines)
check((root / 'v4').exists() and (root / 'v6').exists() and (root / 'll').exists(), 'the interface must end fully addressed after the flap')

# --- command overrides are a test seam only: without TRAVELPI_TEST=1 a hostile
# TRAVELPI_IP/SYSTEMCTL/NMCLI must never be executed (the keeper runs as root).
def hostile_run(test_flag):
    root = Path(_mkdtemp(prefix='travelpi-ap-hostile-'))
    marker = root / 'marker'
    evil = root / 'evil'
    evil.write_text('#!/bin/sh\necho pwned >> "%s"\nexit 0\n' % marker)
    evil.chmod(0o755)
    sysroot = root / 'sys'
    (sysroot / 'class' / 'net' / 'wlan1').mkdir(parents=True)
    (root / 'hostapd.conf').write_text('interface=wlan1\n')
    env = dict(os.environ, TRAVELPI_IP=str(evil), TRAVELPI_SYSTEMCTL=str(evil), TRAVELPI_NMCLI=str(evil),
               TRAVELPI_HOSTAPD_CONF=str(root / 'hostapd.conf'), TRAVELPI_SYS_ROOT=str(sysroot))
    env.pop('TRAVELPI_TEST', None)
    if test_flag:
        env['TRAVELPI_TEST'] = '1'
    subprocess.run(['/bin/sh', str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    return marker.exists()


check(hostile_run(True), 'control: with TRAVELPI_TEST=1 the override is honored (test seam works)')
check(not hostile_run(False), 'without TRAVELPI_TEST=1 a hostile TRAVELPI_IP/SYSTEMCTL/NMCLI must NOT be executed')

if failures:
    print('script ap-keeper FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('script ap-keeper checks passed')
