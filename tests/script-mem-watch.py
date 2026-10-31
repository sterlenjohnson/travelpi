#!/usr/bin/env python3
"""systemd/travelpi-mem-watch run for real under PATH shims.

The loop reads a fake /proc/meminfo and writes state/run files in a sandbox
(TRAVELPI_MEMINFO, TRAVELPI_STATE_DIR, TRAVELPI_RUN_DIR). Shims stand in for
systemctl, ps and logger; the sleep shim ends the loop after N passes. The
processes ps reports are real sleeping children, so `kill -9` really lands and
the test checks who is still alive.

Pinned: under low memory the optional services stop before anything is killed
(exim4, then adguardhome, then a SIGKILL); protected names (including the
15-character kernel-truncated ones), pid <= 2 and kernel threads are never the
victim; the JSON event name is sanitised so a hostile process name cannot
break the log line; a spent kill budget holds instead of killing; healthy
memory restores a guard-stopped adguardhome only after 20 minutes.
"""
import json
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'systemd' / 'travelpi-mem-watch'
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


SHIMS = {
    'logger': 'echo "logger $*" >> "$SHIM_LOG"\n',
    'systemctl': (
        'echo "systemctl $*" >> "$SHIM_LOG"\n'
        'case "$1" in\n'
        '  is-active) [ -e "$SHIM_DIR/active-$3" ];;\n'    # systemctl is-active --quiet NAME
        '  stop) rm -f "$SHIM_DIR/active-$2";;\n'
        '  start) : > "$SHIM_DIR/active-$2";;\n'
        'esac\n'),
    'ps': 'cat "$SHIM_DIR/ps-output"\n',
    'sleep': ('n=$(cat "$SHIM_DIR/loops" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$SHIM_DIR/loops"\n'
              'if [ "$n" -ge "$MAX_LOOPS" ]; then kill -TERM "$PPID"; fi\n'),
}


class Procs:
    """Real sleeping children standing in for the processes `ps` lists."""

    def __init__(self):
        self.children = {}

    def spawn(self, label):
        child = subprocess.Popen(['sleep', '600'])
        self.children[label] = child
        return child.pid

    def alive(self, label):
        return self.children[label].poll() is None

    def reap(self):
        for child in self.children.values():
            if child.poll() is None:
                child.kill()
            child.wait()


def ps_listing(procs, protected_only=False):
    """ps -eo rss=,pid=,comm= --sort=-rss: protected processes are the biggest
    on purpose, so only a correct filter picks the right victim."""
    lines = ['900000 %d hostapd' % procs.spawn('hostapd'),
             '800000 %d travelpi-cockpi' % procs.spawn('cockpit'),    # 15-char truncated protected name
             '700000 %d systemd-journal' % procs.spawn('journal'),
             '600000 %d sh' % procs.spawn('sh'),
             '500000 2 kthreadd',                                      # pid <= 2
             '450000 %d [kworker/0:1]' % procs.spawn('kworker'),       # kernel thread
             '400000 1 systemd']
    if not protected_only:
        lines.append('300000 %d we"ird$name' % procs.spawn('victim'))  # hostile comm
        lines.append('200000 %d chromium' % procs.spawn('small'))
    return '\n'.join(lines) + '\n'


def run_watch(loops, mem_mb=20, swap_mb=500, active=('exim4', 'adguardhome'), preload=None, flag=False,
              since=None, procs=None, protected_only=False):
    root = Path(tempfile.mkdtemp(prefix='travelpi-mem-watch-'))
    state, run_dir, shims = root / 'state', root / 'run', root / 'bin'
    for d in (state, run_dir, shims):
        d.mkdir()
    (root / 'meminfo').write_text('MemTotal:  400000 kB\nMemAvailable: %d kB\nSwapFree: %d kB\n' % (mem_mb * 1024, swap_mb * 1024))
    (root / 'ps-output').write_text(ps_listing(procs, protected_only) if procs else '')
    for name in active:
        (root / ('active-' + name)).write_text('')
    for name, body in SHIMS.items():
        shim = shims / name
        shim.write_text('#!/bin/sh\n' + body)
        shim.chmod(0o755)
    if preload:
        (state / 'mem-guard.jsonl').write_text(preload)
    if flag:
        (run_dir / 'travelpi-mem-guard-stopped-adguard').write_text('')
    if since is not None:
        (run_dir / 'travelpi-mem-guard-recovery-since').write_text('%d\n' % since)
    env = dict(os.environ, PATH=str(shims) + os.pathsep + os.environ['PATH'], SHIM_LOG=str(root / 'shim.log'),
               SHIM_DIR=str(root), MAX_LOOPS=str(loops), TRAVELPI_MEMINFO=str(root / 'meminfo'),
               TRAVELPI_STATE_DIR=str(state), TRAVELPI_RUN_DIR=str(run_dir))
    proc = subprocess.run(['/bin/sh', str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    return root, proc


def shim_lines(root):
    log = root / 'shim.log'
    return log.read_text().splitlines() if log.exists() else []


def guard_events(root):
    log = root / 'state' / 'mem-guard.jsonl'
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def actions(root):
    return [e['action'] for e in guard_events(root)]


def starts_service(root):
    return [l for l in shim_lines(root) if l.startswith('systemctl start')]


# --- ladder order under pressure: exim4, adguardhome, then the kill.
procs = Procs()
root, proc = run_watch(loops=3, procs=procs)
time.sleep(0.2)
check(proc.returncode in (-15, 143), 'the loop must run until stopped: rc=%s %s' % (proc.returncode, proc.stderr))
check(actions(root) == ['stop-exim4', 'stop-adguardhome', 'kill'], 'optional services must stop before anything is killed: %s' % actions(root))
stops = [l for l in shim_lines(root) if l.startswith('systemctl stop')]
check(stops == ['systemctl stop exim4', 'systemctl stop adguardhome'], 'each pressure pass stops one optional service: %s' % stops)
check(not procs.alive('victim'), 'the largest unprotected process must be SIGKILLed')
for label in ('hostapd', 'cockpit', 'journal', 'sh', 'kworker', 'small'):
    check(procs.alive(label), 'only the chosen victim may die; %s was killed' % label)
check((root / 'state' / 'mem-watch-heartbeat').exists(), 'the heartbeat must be written')
check((root / 'run' / 'travelpi-mem-guard-stopped-adguard').exists(), 'stopping adguardhome must leave the heal flag')
kill_event = guard_events(root)[-1]
check(kill_event['mem_avail_mb'] == 20 and kill_event['swap_free_mb'] == 500, 'the event carries the readings: %s' % kill_event)
detail = kill_event['detail']
check('we_ird_name' in detail and '$' not in detail and detail.count('"') == 0,
      'a hostile process name must be sanitised in the JSON event: %s' % detail)
check(all(isinstance(e['ts'], str) and e['ts'].endswith('Z') for e in guard_events(root)), 'event timestamps are UTC ISO strings')
procs.reap()
shutil.rmtree(root)

# --- protected names, pid <= 2 and kernel threads are never killed, even with no other candidate.
procs = Procs()
root, proc = run_watch(loops=3, active=(), procs=procs, protected_only=True)
time.sleep(0.2)
check(all(procs.alive(label) for label in procs.children), 'protected processes must survive: %s' %
      {k: procs.alive(k) for k in procs.children})
check('kill' not in actions(root), 'no kill event when only protected processes remain: %s' % actions(root))
procs.reap()
shutil.rmtree(root)

# --- the kill budget: eight recent kills hold the line instead of another SIGKILL.
now = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
spent = ''.join(json.dumps({'ts': now, 'action': 'kill', 'mem_avail_mb': 20, 'swap_free_mb': 500, 'detail': 'earlier'},
                           separators=(',', ':')) + '\n' for _ in range(8))
procs = Procs()
root, proc = run_watch(loops=2, active=(), preload=spent, procs=procs)
time.sleep(0.2)
check(procs.alive('victim'), 'a spent kill budget must not kill again')
check(actions(root)[-1] == 'pressure', 'a spent budget must log "pressure": %s' % actions(root))
procs.reap()
shutil.rmtree(root)

# --- swap pressure alone triggers the same ladder.
root, proc = run_watch(loops=1, mem_mb=300, swap_mb=10)
check(actions(root) == ['stop-exim4'], 'low swap alone must start the ladder: %s' % actions(root))
shutil.rmtree(root)

# --- healthy memory: nothing happens, and a guard-stopped adguardhome returns only after 20 minutes.
healthy = dict(mem_mb=300, swap_mb=300, active=())
root, proc = run_watch(loops=2, **healthy)
check(guard_events(root) == [] and not [l for l in shim_lines(root) if l.startswith('systemctl')], 'healthy memory must do nothing')
shutil.rmtree(root)

now_s = int(time.time())
root, proc = run_watch(loops=1, flag=True, since=now_s - 100, **healthy)
check(not starts_service(root), 'adguardhome must not return before 20 minutes of health')
check((root / 'run' / 'travelpi-mem-guard-stopped-adguard').exists(), 'the heal flag stays until the service is restored')
shutil.rmtree(root)

root, proc = run_watch(loops=1, flag=True, since=now_s - 1300, **healthy)
check(starts_service(root) == ['systemctl start adguardhome'], 'adguardhome must be restarted after 20 healthy minutes: %s' % shim_lines(root))
check(actions(root) == ['heal-adguardhome'] and not (root / 'run' / 'travelpi-mem-guard-stopped-adguard').exists(),
      'the heal must be logged and the flag cleared: %s' % actions(root))
shutil.rmtree(root)

# --- pressure returning resets the recovery clock and blocks the heal.
root, proc = run_watch(loops=1, flag=True, since=now_s - 1300, mem_mb=10, swap_mb=500, active=())
check(not (root / 'run' / 'travelpi-mem-guard-recovery-since').exists(), 'pressure must reset the recovery timer')
check(not starts_service(root), 'no heal while under pressure')
shutil.rmtree(root)

if failures:
    print('script mem-watch FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('script mem-watch checks passed')
