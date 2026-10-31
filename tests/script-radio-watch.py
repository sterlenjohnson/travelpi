#!/usr/bin/env python3
"""systemd/travelpi-radio-watch run for real under PATH shims.

The watchdog loop runs against a fake sysfs, hostapd.conf, /proc/uptime and
state dir (the script's TRAVELPI_* overrides). Shims stand in for ip,
systemctl, logger, date and sleep; the sleep shim advances the fake uptime by
the slept seconds and ends the loop after a set number of 15 s passes.

Pinned: the heartbeat is written; a carrier-down streak reaches the repair
ladder only at the streak limit, and then in order (link cycle, USB rebind,
hostapd restart); a recovered carrier clears the streak; a link cycle that
works stops the ladder there; the cooldown between recoveries runs on uptime
(a wildly jumping wall clock changes nothing) and expires after COOLDOWN
uptime seconds.
"""
import json
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import atexit


def _mkdtemp(prefix):
    """Temp dir removed at interpreter exit, even on failure."""
    path = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, path, True)
    return path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'systemd' / 'travelpi-radio-watch'
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


SHIMS = {
    'logger': 'echo "logger $*" >> "$SHIM_LOG"\n',
    'systemctl': 'echo "systemctl $*" >> "$SHIM_LOG"\n',
    'ip': ('echo "ip $*" >> "$SHIM_LOG"\n'
           'if [ "${FIX_AT:-}" = link ] && [ "$1 $2 $4" = "link set up" ]; then echo 1 > "$FAKE_SYS/class/net/$3/carrier"; fi\n'),
    # a wall clock that jumps by days on every call (no RTC, NTP step)
    'date': ('n=$(cat "$SHIM_DIR/date-n" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_DIR/date-n"\n'
             'echo $((1700000000 + n * 400000))\n'),
    'sleep': ('echo "sleep $1" >> "$SHIM_LOG"\n'
              'up=$(cut -d. -f1 "$TRAVELPI_PROC_UPTIME"); echo "$((up + $1)).00 0.00" > "$TRAVELPI_PROC_UPTIME"\n'
              'if [ "$1" = 15 ]; then\n'
              '  n=$(cat "$SHIM_DIR/loops" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_DIR/loops"\n'
              '  if [ "$n" -ge "$MAX_LOOPS" ]; then kill -TERM "$PPID"; fi\n'
              'fi\n'),
}


def run_watch(loops, carrier='0', uptime=1000, streak=None, fix_at=None, last_recovery=None, wall_clock_jumps=True):
    root = Path(_mkdtemp(prefix='travelpi-radio-watch-'))
    sysroot, state, run_dir, shims = root / 'sys', root / 'state', root / 'run', root / 'bin'
    dev = sysroot / 'devices' / 'usb1' / '1-1' / '1-1.2' / '1-1.2:1.0'
    dev.mkdir(parents=True)
    (sysroot / 'class' / 'net' / 'wlan1').mkdir(parents=True)
    (sysroot / 'class' / 'net' / 'wlan1' / 'carrier').write_text(carrier + '\n')
    (sysroot / 'class' / 'net' / 'wlan1' / 'device').symlink_to(dev)
    (sysroot / 'bus' / 'usb' / 'drivers' / 'usb' / '1-1.2').mkdir(parents=True)
    hostapd = root / 'hostapd.conf'
    hostapd.write_text('driver=nl80211\ninterface=wlan1\nssid=TravelPi\n')
    uptime_file = root / 'uptime'
    uptime_file.write_text('%d.00 0.00\n' % uptime)
    shims.mkdir()
    for name, body in SHIMS.items():
        if name == 'date' and not wall_clock_jumps:
            continue
        shim = shims / name
        shim.write_text('#!/bin/sh\n' + body)
        shim.chmod(0o755)
    run_dir.mkdir(mode=0o700)
    if streak is not None:
        (run_dir / 'streak').write_text('%d\n' % streak)
    if last_recovery is not None:
        (run_dir / 'last-recovery-uptime').write_text('%d\n' % last_recovery)
    env = dict(os.environ, PATH=str(shims) + os.pathsep + os.environ['PATH'],
               SHIM_LOG=str(root / 'shim.log'), SHIM_DIR=str(root), MAX_LOOPS=str(loops),
               FAKE_SYS=str(sysroot), TRAVELPI_SYS_ROOT=str(sysroot), TRAVELPI_STATE_DIR=str(state),
               TRAVELPI_RADIO_WATCH_RUN=str(run_dir), TRAVELPI_HOSTAPD_CONF=str(hostapd),
               TRAVELPI_PROC_UPTIME=str(uptime_file))
    if fix_at:
        env['FIX_AT'] = fix_at
    proc = subprocess.run(['/bin/sh', str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    return root, proc


def shim_lines(root):
    log = root / 'shim.log'
    return log.read_text().splitlines() if log.exists() else []


def events(root):
    log = root / 'state' / 'radio-recoveries.jsonl'
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def finished_by_shim(proc):
    return proc.returncode in (-15, 143)


def commands(root, tool):
    return [line for line in shim_lines(root) if line.startswith(tool + ' ')]


# --- the heartbeat is written, and one down pass is not yet an escalation.
root, proc = run_watch(loops=1)
check(finished_by_shim(proc), 'the loop must keep running until stopped: rc=%s %s' % (proc.returncode, proc.stderr))
check((root / 'state' / 'radio-watch-heartbeat').exists(), 'the heartbeat must be written on every pass')
check((root / 'run' / 'streak').read_text().strip() == '1', 'the first no-carrier pass must start a streak of 1')
check(not commands(root, 'ip') and not commands(root, 'systemctl') and events(root) == [],
      'a single no-carrier pass must not touch the radio: %s' % shim_lines(root))
check(oct((root / 'run').stat().st_mode & 0o777) == '0o700', 'the run dir must stay root-only (0700)')
shutil.rmtree(root)

# --- carrier up clears the streak and never escalates.
root, proc = run_watch(loops=2, carrier='1', streak=1)
check((root / 'run' / 'streak').read_text().strip() == '0', 'a recovered carrier must reset the streak')
check(events(root) == [] and not commands(root, 'ip'), 'a healthy carrier must not run the ladder')
shutil.rmtree(root)

# --- the ladder: link cycle, then USB rebind, then hostapd restart, in order.
root, proc = run_watch(loops=2)
lines = shim_lines(root)
check(finished_by_shim(proc), 'ladder run must end by the test shim: rc=%s %s' % (proc.returncode, proc.stderr))
messages = [line for line in lines if line.startswith('logger ')]
order = [m for m in messages if any(k in m for k in ('escalating', 'link cycle', 'usb rebind', 'hostapd restart', 'outcome'))]
check(len(order) == 5 and 'escalating' in order[0] and 'link cycle' in order[1] and 'usb rebind 1-1.2' in order[2]
      and 'hostapd restart' in order[3] and 'outcome: stalled' in order[4],
      'the repair ladder must run link cycle, USB rebind, hostapd restart in order: %s' % order)
check(commands(root, 'ip')[:2] == ['ip link set wlan1 down', 'ip link set wlan1 up'], 'the link cycle must down then up the AP radio: %s' % commands(root, 'ip'))
check(commands(root, 'systemctl') == ['systemctl restart --no-block hostapd'], 'the last rung restarts hostapd without blocking: %s' % commands(root, 'systemctl'))
sleeps = [line.split()[1] for line in lines if line.startswith('sleep ')]
check(sleeps == ['15', '2', '10', '3', '12', '8', '15'],
      'the settle waits must separate the rungs (2/10, 3/12, 8): %s' % sleeps)
usb = root / 'sys' / 'bus' / 'usb' / 'drivers' / 'usb'
check((usb / 'unbind').read_text().strip() == '1-1.2' and (usb / 'bind').read_text().strip() == '1-1.2',
      'the USB device (not its interface) must be unbound and rebound')
check(events(root) and events(root)[-1].get('outcome') == 'stalled' and isinstance(events(root)[-1].get('ts'), int),
      'a ladder that never restores carrier must record "stalled": %s' % events(root))
check(len(events(root)) == 1, 'one escalation must record exactly one event')
check((root / 'run' / 'streak').read_text().strip() == '0', 'the streak resets after a recovery attempt')
check((root / 'run' / 'last-recovery-uptime').read_text().strip().isdigit(), 'the cooldown stamp must be an uptime reading')
shutil.rmtree(root)

# --- a link cycle that works stops the ladder at the first rung.
root, proc = run_watch(loops=2, fix_at='link')
check([e['outcome'] for e in events(root)] == ['link-cycle'], 'a working link cycle must be the recorded outcome: %s' % events(root))
check(not commands(root, 'systemctl') and not (root / 'sys' / 'bus' / 'usb' / 'drivers' / 'usb' / 'unbind').exists(),
      'a working link cycle must not rebind USB or restart hostapd')
shutil.rmtree(root)

# --- cooldown runs on uptime. Wall clock jumps ~4.6 days per date call and must not matter.
root, proc = run_watch(loops=6, uptime=5000)
check(len(events(root)) == 1, 'inside the cooldown a persisting outage must not escalate again (events=%s)' % events(root))
check(int((root / 'run' / 'streak').read_text()) >= 2, 'the streak keeps counting while the cooldown holds')
check(int((root / 'shim.log').read_text().count('link cycle')) == 1, 'only one link cycle inside the cooldown')
shutil.rmtree(root)

root, proc = run_watch(loops=20, uptime=5000)
check(len(events(root)) == 2, 'after COOLDOWN uptime seconds a second recovery must run (events=%s)' % events(root))
shutil.rmtree(root)

if failures:
    print('script radio-watch FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('script radio-watch checks passed')
