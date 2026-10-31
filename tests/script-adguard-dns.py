#!/usr/bin/env python3
"""systemd/travelpi-adguard-hotel-dns (NetworkManager dispatcher) end to end.

Run as the dispatcher runs it, with $1 interface, $2 action and
DHCP4_NAMESERVERS, against a sandbox AdGuardHome.yaml (ADGUARD_YAML) and PATH
shims for tailscale, systemctl, logger and ip.

Pinned: a wlan0 dhcp4-change rewrites upstream_dns to the tailnet split lines
(one per MagicDNS domain), optional home forwards and the DHCP resolvers, and
leaves every other key (bootstrap_dns, bind_hosts, fallback_dns) alone; the
yaml ends mode 0640 with no temp files left behind; AdGuard is restarted;
events on another interface, other actions, a missing yaml or an empty/garbage
nameserver list change nothing; eth0 counts only while it holds the default
route.
"""
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import re
import stat
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
SCRIPT = ROOT / 'systemd' / 'travelpi-adguard-hotel-dns'
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


YAML = '''\
http:
  address: 0.0.0.0:80
dns:
  bind_hosts:
    - 0.0.0.0
  upstream_dns:
    - 1.1.1.1
    - "[/old.example/]10.9.9.9"
    - 9.9.9.9
  fallback_dns: []
  upstream_dns_file: ""
  bootstrap_dns:
    - 9.9.9.10
users: []
'''

TAILSCALE_JSON = '''{"Self": {"DNSName": "node-one.tailnet-one.ts.net."},
 "Peer": {"a": {"DNSName": "node-two.tailnet-two.ts.net."}, "b": {"DNSName": "node-three.tailnet-one.ts.net."}}}'''

SHIMS = {
    'tailscale': 'echo "tailscale $*" >> "$SHIM_LOG"\ncat "$SHIM_DIR/tailscale.json" 2>/dev/null\n',
    'systemctl': 'echo "systemctl $*" >> "$SHIM_LOG"\n',
    'logger': 'echo "logger $*" >> "$SHIM_LOG"\n',
    'ip': 'echo "ip $*" >> "$SHIM_LOG"\nif [ -e "$SHIM_DIR/eth0-default" ]; then echo "default via 192.0.2.1 dev eth0"; fi\n',
}


def gnu_sed():
    try:
        return subprocess.run(['sed', '--version'], capture_output=True, text=True).returncode == 0
    except OSError:
        return False


def dispatch(iface='wlan0', action='dhcp4-change', nameservers='192.0.2.1 192.0.2.2', yaml=YAML, mode=0o644,
             tailscale=TAILSCALE_JSON, eth0_default=False, home=None, env_extra=None):
    root = Path(_mkdtemp(prefix='travelpi-adguard-dns-'))
    (root / 'bin').mkdir()
    for name, body in SHIMS.items():
        shim = root / 'bin' / name
        shim.write_text('#!/bin/sh\n' + body)
        shim.chmod(0o755)
    conf = root / 'conf'
    conf.mkdir()
    cfg = conf / 'AdGuardHome.yaml'
    if yaml is not None:
        cfg.write_text(yaml)
        cfg.chmod(mode)
    if tailscale:
        (root / 'tailscale.json').write_text(tailscale)
    if eth0_default:
        (root / 'eth0-default').write_text('')
    env = dict(os.environ, PATH=str(root / 'bin') + os.pathsep + os.environ['PATH'], SHIM_LOG=str(root / 'shim.log'),
               SHIM_DIR=str(root), ADGUARD_YAML=str(cfg), DHCP4_NAMESERVERS=nameservers,
               TRAVELPI_HOME_DNS=str(root / 'home-dns'))
    if home is not None:
        (root / 'home-dns').write_text(home)
    env.update(env_extra or {})
    proc = subprocess.run(['/bin/sh', str(SCRIPT), iface, action], env=env, capture_output=True, text=True, timeout=60)
    return root, cfg, proc


def shim_lines(root):
    log = root / 'shim.log'
    return log.read_text().splitlines() if log.exists() else []


def upstream_block(text):
    block = []
    inside = False
    for line in text.splitlines():
        if re.match(r'^\s*upstream_dns:', line):
            inside = True
            continue
        if inside:
            if re.match(r'^\s*- ', line):
                block.append(line.strip()[2:])
            else:
                break
    return block


def unchanged(root, cfg, label, proc):
    check(proc.returncode == 0, label + ': must exit 0: ' + proc.stderr)
    check(cfg.read_text() == YAML if cfg.exists() else True, label + ': yaml must be untouched')
    check(not [l for l in shim_lines(root) if l.startswith('systemctl')], label + ': AdGuard must not be restarted')
    check(sorted(p.name for p in cfg.parent.iterdir()) == ['AdGuardHome.yaml'] if cfg.exists() else True,
          label + ': no temp files may be left behind')


# --- wlan0 dhcp4-change rewrites upstream_dns.
root, cfg, proc = dispatch(home='home.example 100.64.0.9\nbad line here too\n')
text = cfg.read_text()
check(proc.returncode == 0, 'dispatch must exit 0: ' + proc.stderr)
block = upstream_block(text)
check(block == ['"[/tailnet-one.ts.net/]100.100.100.100"', '"[/tailnet-two.ts.net/]100.100.100.100"',
                '"[/home.example/]100.64.0.9"', '192.0.2.1', '192.0.2.2'],
      'upstream_dns must be tailnet splits, home forward, then the DHCP resolvers: %s' % block)
check('1.1.1.1' not in text and '9.9.9.9' not in text and 'old.example' not in text, 'the previous upstreams must be replaced')
check(not any(line.startswith('"[/.') or '[/.' in line for line in block), 'a leading-dot split pattern crashes AdGuard and must never be emitted')
for kept in ('address: 0.0.0.0:80', '  bind_hosts:\n    - 0.0.0.0', '  bootstrap_dns:\n    - 9.9.9.10', 'users: []', '  upstream_dns_file: ""'):
    check(kept in text, 'unrelated yaml must be preserved: %r' % kept)
check(stat.S_IMODE(cfg.stat().st_mode) == 0o640, 'AdGuardHome.yaml must end mode 0640, got %o' % stat.S_IMODE(cfg.stat().st_mode))
check(sorted(p.name for p in cfg.parent.iterdir()) == ['AdGuardHome.yaml'], 'no temp files may remain beside the yaml: %s' % list(cfg.parent.iterdir()))
check('systemctl restart adguardhome.service' in shim_lines(root), 'AdGuard must be restarted to read the new upstreams: %s' % shim_lines(root))
check(any(l.startswith('logger') and '192.0.2.1' in l and 'tailnet-one.ts.net' in l for l in shim_lines(root)), 'the change must be logged')
if gnu_sed():
    check('127.0.0.1:5335' in text, 'Unbound must be added as fallback_dns')
    check(re.search(r'^  nat64_prefix: "64:ff9b::/96"$', text, re.M), 'the DNS64 prefix must be added once at two-space indent')
    root2, cfg2, proc2 = dispatch(yaml=text, home='home.example 100.64.0.9\nbad line here too\n')
    check(cfg2.read_text().count('nat64_prefix') == 1 and cfg2.read_text().count('127.0.0.1:5335') == 1,
          'a second run must be idempotent for fallback_dns and nat64_prefix')
    check(upstream_block(cfg2.read_text()) == block, 'a second run must produce the same upstreams')

# --- up works like dhcp4-change; a 0600 yaml still ends 0640 (the dispatcher normalises it).
root, cfg, proc = dispatch(action='up', mode=0o600)
check(upstream_block(cfg.read_text())[-2:] == ['192.0.2.1', '192.0.2.2'] and stat.S_IMODE(cfg.stat().st_mode) == 0o640,
      'an "up" event must rewrite too, normalising to 0640')

# --- no tailnet: only the DHCP resolvers.
root, cfg, proc = dispatch(tailscale='')
check(upstream_block(cfg.read_text()) == ['192.0.2.1', '192.0.2.2'], 'without a tailnet only the hotel resolvers remain: %s' % upstream_block(cfg.read_text()))

# --- garbage in DHCP4_NAMESERVERS is filtered, never written into the yaml.
root, cfg, proc = dispatch(nameservers='192.0.2.1 evil;rm 2001:db8::1 $(id) 192.0.2.2 192.0.2.3 192.0.2.4')
check(upstream_block(cfg.read_text())[-3:] == ['192.0.2.1', '192.0.2.2', '192.0.2.3'] and 'evil' not in cfg.read_text()
      and '2001:db8' not in cfg.read_text() and '192.0.2.4' not in cfg.read_text(),
      'only the first three IPv4 resolvers may be written: %s' % upstream_block(cfg.read_text()))

# --- nothing to do: each leaves the yaml untouched and AdGuard running.
for label, kwargs in (('other interface (AP lease)', dict(iface='wlan1')),
                      ('tailscale0', dict(iface='tailscale0')),
                      ('down event', dict(action='down')),
                      ('dhcp6-change event', dict(action='dhcp6-change')),
                      ('no nameservers', dict(nameservers='')),
                      ('only non-IPv4 nameservers', dict(nameservers='2001:db8::1 name.example')),
                      ('eth0 without the default route', dict(iface='eth0'))):
    root, cfg, proc = dispatch(**kwargs)
    unchanged(root, cfg, label, proc)

# --- eth0 counts only while it holds the default route.
root, cfg, proc = dispatch(iface='eth0', eth0_default=True)
check(upstream_block(cfg.read_text())[-2:] == ['192.0.2.1', '192.0.2.2'], 'eth0 holding the default route must rewrite: %s' % upstream_block(cfg.read_text()))

# --- no AdGuard yaml: exit quietly.
root, cfg, proc = dispatch(yaml=None)
check(proc.returncode == 0 and not cfg.exists() and not [l for l in shim_lines(root) if l.startswith('systemctl')],
      'a host without AdGuard must be left alone: rc=%s' % proc.returncode)

if failures:
    print('script adguard-dns FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('script adguard-dns checks passed')
