#!/usr/bin/env python3
"""Secret-leak sentinel: every secret-taking path is run with a unique
sentinel through a recording HOST, and the sentinel may appear only where it
is meant to (stdin for nmcli, the 0600 key file for tailscale, hostapd.conf
for the AP passphrase).

Covered: connect_hotel password, set_ap_identity passphrase, tailscale_auth
authkey, and the WireGuard dump parser / vpn_status / status() fed a dump
that carries private and preshared key sentinels. The sentinel must never
reach any recorded argv, captured stdout/stderr, an action response, a status
payload, a cache file or any other file the helper wrote, and the key file
must be 0600 and gone after the call. set_ap_identity must leave hostapd.conf
0600 (even when it started 0644), keep its backup 0600 while it exists and
remove it once the change is applied or rolled back.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import stat
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

path = Path(__file__).parents[1] / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


class Result:
    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingHost:
    """Records argv and stdin of every call; answers a minimal host."""

    def __init__(self, sentinel, wg_dump='', connect_rc=0, restart_rc=0, login_rc=0):
        self.sentinel = sentinel
        self.wg_dump = wg_dump
        self.connect_rc = connect_rc
        self.restart_rc = restart_rc
        self.login_rc = login_rc
        self.argvs = []
        self.stdins = []
        self.key_files = []  # (path, mode, content, existed) observed at login time
        self.backup_seen = []  # (mode, content) of the hostapd backup at each hostapd restart

    def run(self, argv, **kwargs):
        self.argvs.append(list(argv))
        if kwargs.get('input_text'):
            self.stdins.append(kwargs['input_text'])
        if argv[:2] == ['/usr/bin/tailscale', 'login']:
            key_path = argv[2].split('file:', 1)[1]
            info = os.stat(key_path)
            self.key_files.append((key_path, stat.S_IMODE(info.st_mode), Path(key_path).read_text(), True))
            return Result(self.login_rc, '', 'login failed' if self.login_rc else '')
        if argv[:3] == ['/usr/bin/wg', 'show', 'wg0']:
            return Result(0, self.wg_dump)
        if argv[:2] == ['/bin/systemctl', 'is-active']:
            return Result(0, 'active\n' if argv[2] in ('wg-quick@wg0', 'travelpi-sqm.service') else 'inactive\n')
        if argv[:2] == ['/bin/systemctl', 'restart'] and argv[2] == 'hostapd':
            for backup in helper.HOSTAPD.parent.glob('*.travelpi-backup'):
                self.backup_seen.append((stat.S_IMODE(backup.stat().st_mode), backup.read_text()))
            return Result(self.restart_rc)
        if argv[:5] == ['/usr/bin/nmcli', '-t', '-f', 'NAME,DEVICE', 'connection']:
            return Result(0, 'HotelWiFi:wlan0\n')
        if argv[:4] == ['/usr/bin/nmcli', '-w', '30', '--ask'] or ('wifi' in argv and 'connect' in argv):
            # A hostile nmcli that echoes what it was fed on failure.
            return Result(self.connect_rc, '', ('Error: Secrets were required, but not provided (%s)' % self.sentinel)
                          if self.connect_rc else '')
        return Result(0, '')


def leaks(sentinel, *haystacks):
    return [i for i, hay in enumerate(haystacks) if sentinel in (hay if isinstance(hay, str) else json.dumps(hay, default=str))]


sandbox = Path(_mkdtemp(prefix='travelpi-secret-leak-'))
for name in ('STATUS_CACHE', 'PORTAL_CACHE', 'JOURNAL_EVENTS_CACHE', 'TAILSCALE_STATUS_CACHE'):
    setattr(helper, name, str(sandbox / (name.lower() + '.json')))
helper.SQM_ENV_FILE = str(sandbox / 'sqm-env')
helper.HOSTAPD = sandbox / 'hostapd.conf'

saved = (helper.HOST, helper.probe, helper.EUID)
helper.probe = lambda *a, **k: {'status': 'INTERNET_OK'}
helper.EUID = lambda: 0


def run_action(host, name, **fields):
    """Run through the real CLI entry (stdin JSON) and the module entry; return
    (responses, captured stdout, captured stderr)."""
    helper.HOST = host
    out, err = io.StringIO(), io.StringIO()
    request = {'action': name, 'confirm': True, **fields}
    old_argv, old_stdin = sys.argv, sys.stdin
    try:
        sys.argv = ['travelpi-cockpit', 'action']
        sys.stdin = io.StringIO(json.dumps(request))
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            helper.main()
            direct = helper.action(name, dict(request))
    finally:
        sys.argv, sys.stdin = old_argv, old_stdin
    return [json.loads(out.getvalue().splitlines()[0]), direct], out.getvalue(), err.getvalue()


def scan_files(sentinel, allowed=()):
    bad = []
    for item in sandbox.rglob('*'):
        if item.is_file() and item not in allowed and sentinel in item.read_text(errors='replace'):
            bad.append(str(item))
    return bad


try:
    # --- connect_hotel: success and a failure whose nmcli stderr echoes the secret.
    for rc in (0, 4):
        sentinel = 'SENTINEL-HOTEL-PW-%d-7f3a91' % rc
        host = RecordingHost(sentinel, connect_rc=rc)
        responses, out, err = run_action(host, 'connect_hotel', ssid='HotelWiFi', password=sentinel)
        check(any(sentinel in s for s in host.stdins), 'positive control: the password must reach nmcli on stdin')
        check(not leaks(sentinel, *host.argvs), 'connect_hotel (rc=%d) put the password in argv: %s' % (rc, host.argvs))
        check(not leaks(sentinel, *responses, out, err), 'connect_hotel (rc=%d) leaked the password in a response or stream' % rc)
        check(not scan_files(sentinel), 'connect_hotel (rc=%d) wrote the password to a file: %s' % (rc, scan_files(sentinel)))

    # --- set_ap_identity: success and a failed restart. hostapd.conf ends 0600 even
    # when it started 0644; the backup is 0600 while it exists and gone afterwards.
    OLD_CONF = 'interface=wlan1\nssid=TravelPi\nwpa=2\nwpa_key_mgmt=WPA-PSK\nwpa_passphrase=old-pass-1234\n'
    for restart_rc in (0, 1):
        sentinel = 'SENTINEL-AP-PASS-%d-c41e88' % restart_rc
        conf = helper.HOSTAPD
        conf.write_text(OLD_CONF)
        conf.chmod(0o644)
        for stale in sandbox.glob('*.travelpi-backup'):
            stale.unlink()
        host = RecordingHost(sentinel, restart_rc=restart_rc)
        responses, out, err = run_action(host, 'set_ap_identity', ssid='Camp Van', passphrase=sentinel)
        check(not leaks(sentinel, *host.argvs), 'set_ap_identity (restart rc=%d) put the passphrase in argv' % restart_rc)
        check(not host.stdins, 'set_ap_identity must not feed the passphrase to any command')
        check(not leaks(sentinel, *responses, out, err), 'set_ap_identity (restart rc=%d) leaked the passphrase in a response or stream' % restart_rc)
        check(stat.S_IMODE(conf.stat().st_mode) == 0o600,
              'set_ap_identity (rc=%d) must leave hostapd.conf 0600, got %o' % (restart_rc, stat.S_IMODE(conf.stat().st_mode)))
        check(host.backup_seen and all(mode == 0o600 for mode, _ in host.backup_seen),
              'the hostapd backup must be 0600 while it exists: %s' % [oct(m) for m, _ in host.backup_seen])
        check(not list(sandbox.glob('*.travelpi-backup')),
              'the hostapd backup (old passphrase) must be gone after the call (rc=%d): %s' % (restart_rc, list(sandbox.glob('*.travelpi-backup'))))
        if restart_rc == 0:
            check(sentinel in conf.read_text(), 'the new passphrase must be in hostapd.conf after success')
            check('old-pass-1234' not in conf.read_text(), 'the previous passphrase must not linger in hostapd.conf')
        else:
            check(sentinel not in conf.read_text(), 'a failed restart must not leave the new passphrase in hostapd.conf')
            check(conf.read_text() == OLD_CONF, 'a failed restart must restore the OLD content: %r' % conf.read_text())
            check(any('old-pass-1234' in c for _, c in host.backup_seen), 'positive control: the backup held the old config')
        check(not scan_files(sentinel, allowed=(conf,)), 'set_ap_identity wrote the passphrase outside hostapd.conf: %s' % scan_files(sentinel, (conf,)))

    # --- a restore that itself fails keeps the 0600 backup and says so.
    sentinel = 'SENTINEL-AP-PASS-unrestored-9d2f10'
    conf = helper.HOSTAPD
    conf.write_text(OLD_CONF)
    conf.chmod(0o644)
    host = RecordingHost(sentinel, restart_rc=1)
    real_restore = helper.restore_hostapd_config

    def broken_restore():
        raise OSError('disk gone')
    helper.restore_hostapd_config = broken_restore
    try:
        helper.HOST = host
        result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True, 'passphrase': sentinel})
    finally:
        helper.restore_hostapd_config = real_restore
    check(result.get('error', {}).get('code') == 'ap_identity_failed_unrestored', 'a failed restore must be *_unrestored: %s' % result)
    backups = list(sandbox.glob('*.travelpi-backup'))
    check(len(backups) == 1 and stat.S_IMODE(backups[0].stat().st_mode) == 0o600 and backups[0].read_text() == OLD_CONF,
          'an unrestored failure must keep the 0600 backup of the old config: %s' % backups)
    check(not leaks(sentinel, result), 'the unrestored response must not echo the passphrase')
    for stale in backups:
        stale.unlink()

    # --- tailscale_auth: key file is 0600 while it exists, and removed afterwards.
    for login_rc in (0, 1):
        sentinel = 'FIXTURE-AUTHKEY-SENTINEL-%d-5d02bb' % login_rc
        host = RecordingHost(sentinel, login_rc=login_rc)
        responses, out, err = run_action(host, 'tailscale_auth', authkey=sentinel)
        check(len(host.key_files) == 2, 'tailscale login must run once per call (CLI and direct)')
        for key_path, mode, content, _ in host.key_files:
            check(mode == 0o600, 'the auth key file must be 0600, got %o' % mode)
            check(content.strip() == sentinel, 'positive control: the key reaches the key file')
            check(not os.path.exists(key_path), 'the auth key file must be removed after the call: ' + key_path)
        check(not leaks(sentinel, *host.argvs), 'tailscale_auth put the key in argv: %s' % host.argvs)
        check(not leaks(sentinel, *responses, out, err), 'tailscale_auth (rc=%d) leaked the key in a response or stream' % login_rc)
        check(not scan_files(sentinel), 'tailscale_auth left the key in a file: %s' % scan_files(sentinel))
    # a refused key (control characters) must not echo or write anything
    sentinel = 'FIXTURE bad SENTINEL-space-91ab'
    host = RecordingHost(sentinel)
    responses, out, err = run_action(host, 'tailscale_auth', authkey=sentinel)
    check(all(r.get('error', {}).get('code') == 'invalid_authkey' for r in responses), 'a malformed key must be refused: %s' % responses)
    check(not leaks(sentinel, *responses, out, err) and not host.key_files, 'a refused key must not be echoed or written')

    # --- WireGuard: private and preshared keys never leave the dump parser.
    private, preshared = 'SENTINEL-WG-PRIVATE-KEY-aa11=', 'SENTINEL-WG-PRESHARED-KEY-bb22='
    dump = ('%s\tSENTINEL-WG-PUBLIC-ok=\t51820\toff\n'
            'peerpublickey1=\t%s\t192.0.2.10:51820\t192.0.2.0/24,2001:db8::/64\t1700000000\t10\t20\t25\n'
            % (private, preshared))
    parsed = helper.parse_wireguard_dump(dump)
    check(parsed['peer_count'] == 1 and parsed['endpoints'] == ['192.0.2.10:51820'], 'the dump must still parse: %s' % parsed)
    check(not leaks(private, parsed) and not leaks(preshared, parsed), 'parse_wireguard_dump leaked a key: %s' % parsed)
    host = RecordingHost(private, wg_dump=dump)
    helper.HOST = host
    vpn = helper.vpn_status()
    check(vpn['providers']['wireguard'].get('peer_count') == 1, 'vpn_status must read the dump: %s' % vpn['providers']['wireguard'])
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        full = helper.status()
        cached = helper.status_cached()
        sys.argv = ['travelpi-cockpit', 'status']
        try:
            helper.main()
        finally:
            sys.argv = ['x']
    for secret in (private, preshared):
        check(not leaks(secret, vpn, full, cached, out.getvalue(), err.getvalue()),
              'WireGuard %s reached vpn_status/status()/CLI output' % secret[:20])
        check(not leaks(secret, *host.argvs), 'a WireGuard key reached argv')
        check(not scan_files(secret), 'a WireGuard key reached a cache file: %s' % scan_files(secret))
finally:
    helper.HOST, helper.probe, helper.EUID = saved

if failures:
    print('secret leak FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('secret leak checks passed')
