#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
from pathlib import Path

path = Path(__file__).parents[1] / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

result = helper.action('set_cake_rate', {
    'action': 'set_cake_rate', 'rate_kbit': '20', 'confirm': True, 'shell': 'ignored'
})
assert result['error']['code'] == 'unknown_fields'

result = helper.action('set_cake_rate', {'action': 'set_cake_rate', 'rate_kbit': '20'})
assert result['error']['code'] == 'confirmation_required'

secret = 'not-for-output'
result = helper.action('connect_hotel', {
    'action': 'connect_hotel', 'ssid': 'hotel', 'password': secret,
    'confirm': True, 'unexpected': True,
})
encoded = json.dumps(result)
assert result['error']['code'] == 'unknown_fields'
assert secret not in encoded

result = helper.action('not_allowed', {'action': 'not_allowed', 'confirm': True})
assert result['error']['code'] == 'unknown_action'

result = helper.action('restart_services', {
    'action': 'restart_services', 'targets': ['systemctl'], 'confirm': True,
})
assert result['error']['code'] == 'invalid_targets'

# CONTEXT.md: role swap is not auto-applied and must surface an honest
# unavailable notice until readiness proves a verified wired management route.
# The helper is the boundary, so it refuses before touching any radio.
result = helper.action('wan_flip', {
    'action': 'wan_flip', 'wan': 'wlan0', 'confirm': True,
})
assert result['error']['code'] == 'unavailable', result
assert 'wired' in result['error']['message'].lower() or 'rollback' in result['error']['message'].lower(), result

class FakeResult:
    returncode = 0
    stdout = ''
    stderr = ''


class FakeHost:
    def __init__(self):
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(argv)
        return FakeResult()


fake = FakeHost()
real_host = helper.HOST
helper.HOST = fake
try:
    result = helper.action('restart_services', {
        'action': 'restart_services', 'targets': ['ap', 'sqm'], 'confirm': True,
    })
finally:
    helper.HOST = real_host
assert result['ok'] is True
assert fake.calls == [['/bin/systemctl', 'restart', 'hostapd'],
                      ['/bin/systemctl', 'restart', helper.SQM_SERVICE]]

# wake_peer: target shape validation + magic packet argv
result = helper.action('wake_peer', {'action': 'wake_peer', 'confirm': True,
                                     'target': 'rm -f /'})
assert result['error']['code'] == 'invalid_target', result
result = helper.action('wake_peer', {'action': 'wake_peer', 'confirm': True})
assert result['error']['code'] == 'invalid_target', result

wake_host = FakeHost()
helper.HOST = wake_host
try:
    result = helper.action('wake_peer', {'action': 'wake_peer', 'confirm': True,
                                         'target': 'home-server'})
finally:
    helper.HOST = real_host
assert result['ok'] is True, result
assert wake_host.calls == [['/usr/bin/tailscale', 'wakeonlan', 'home-server']], wake_host

# Health-page actions: strict allowlists on every free-form field
result = helper.action('set_dns_stack', {'action': 'set_dns_stack', 'confirm': True, 'service': 'cloudflare'})
assert result['error']['code'] == 'invalid_service', result
result = helper.action('set_dns_stack', {'action': 'set_dns_stack', 'confirm': True,
                                         'service': 'unbound', 'upstream': 'evil; rm -rf'})
assert result['error']['code'] == 'invalid_upstream', result
result = helper.action('set_ipv6', {'action': 'set_ipv6', 'confirm': True, 'mode': 'yes'})
assert result['error']['code'] == 'invalid_mode', result
result = helper.action('set_sqm_mode', {'action': 'set_sqm_mode', 'confirm': True, 'mode': 'turbo'})
assert result['error']['code'] == 'invalid_mode', result
result = helper.action('set_cpu_governor', {'action': 'set_cpu_governor', 'confirm': True,
                                            'governor': 'powersave ; reboot'})
assert result['error']['code'] == 'invalid_governor', result

import tempfile

# Governor success: the sysfs write loop runs through the stubbed host
gov_host = FakeHost()
helper.HOST = gov_host
try:
    result = helper.action('set_cpu_governor', {'action': 'set_cpu_governor', 'confirm': True,
                                                'governor': 'performance'})
finally:
    helper.HOST = real_host
assert result['ok'] is True, result
assert any('performance' in ' '.join(call) and 'scaling_governor' in ' '.join(call)
           for call in gov_host.calls), gov_host.calls

# Reclaim: sync + drop_caches, no kills, no service stops
reclaim_host = FakeHost()
helper.HOST = reclaim_host
try:
    result = helper.action('reclaim_memory', {'action': 'reclaim_memory', 'confirm': True})
finally:
    helper.HOST = real_host
assert result['ok'] is True, result
assert any('drop_caches' in ' '.join(call) for call in reclaim_host.calls), reclaim_host.calls
assert not any('systemctl' in ' '.join(call) for call in reclaim_host.calls), reclaim_host.calls

# IPv6 (ADR 0006): networkd owns RAs; no radvd, honest unavailable without the profile
ra_dir = tempfile.mkdtemp(prefix='travelpi-ra-')
orig_net, orig_drop = helper.AP_NETWORK_FILE, helper.AP_RA_OFF_DROPIN
helper.AP_NETWORK_FILE = ra_dir + '/missing.network'
helper.AP_RA_OFF_DROPIN = ra_dir + '/d/ra-off.conf'
ipv6_host = FakeHost()
helper.HOST = ipv6_host
try:
    result = helper.action('set_ipv6', {'action': 'set_ipv6', 'confirm': True, 'mode': 'on'})
    assert result['error']['code'] == 'unavailable', result
    assert ipv6_host.calls == [], ipv6_host.calls
    Path(helper.AP_NETWORK_FILE).write_text('[Match]\nName=wlan1\n')
    helper.ULA_PREFIX_FILE = ra_dir + '/no-ula-prefix'
    result = helper.action('set_ipv6', {'action': 'set_ipv6', 'confirm': True, 'mode': 'on'})
    assert result['error']['code'] == 'unavailable' and 'No ULA prefix' in result['error']['message'], result
    assert ipv6_host.calls == [], ipv6_host.calls
    Path(ra_dir + '/ula-prefix').write_text('fd12:3456:789a:1::/64\n')
    helper.ULA_PREFIX_FILE = ra_dir + '/ula-prefix'
    assert helper.ap_v6_gateway() == 'fd12:3456:789a:1::1/64'
    result = helper.action('set_ipv6', {'action': 'set_ipv6', 'confirm': True, 'mode': 'off'})
    assert result['ok'] is True, result
    assert 'IPv6SendRA=no' in Path(helper.AP_RA_OFF_DROPIN).read_text()
    result = helper.action('set_ipv6', {'action': 'set_ipv6', 'confirm': True, 'mode': 'on'})
    assert result['ok'] is True, result
    assert not Path(helper.AP_RA_OFF_DROPIN).exists()
finally:
    helper.HOST = real_host
    helper.AP_NETWORK_FILE, helper.AP_RA_OFF_DROPIN = orig_net, orig_drop
assert ['/usr/bin/networkctl', 'reconfigure', 'wlan1'] in ipv6_host.calls, ipv6_host.calls
assert not any('radvd' in ' '.join(call) for call in ipv6_host.calls), ipv6_host.calls

# Timeouts become returncode 124 instead of raising; action() never leaks a traceback.
import subprocess
class TimeoutAdapter(helper.HostAdapter):
    pass
orig_sub = helper.subprocess.run
def boom(*a, **k):
    raise subprocess.TimeoutExpired(a[0], 1)
helper.subprocess.run = boom
try:
    timed = helper.HostAdapter().run(['/bin/true'])
finally:
    helper.subprocess.run = orig_sub
assert timed.returncode == 124, timed
class Exploding:
    def run(self, argv, **kwargs):
        raise RuntimeError('secret-detail')
helper.HOST = Exploding()
try:
    result = helper.action('reboot', {'action': 'reboot', 'confirm': True})
finally:
    helper.HOST = real_host
assert result['error']['code'] == 'internal_error' and 'secret-detail' not in json.dumps(result), result

# Upstream nameserver selection: loopback, tailnet resolver and IPv6 are dropped
for bad in ('127.0.0.53', '127.0.0.1', '100.100.100.100', 'fe80::1', '::1', 'junk'):
    assert not helper.usable_upstream(bad), bad
assert helper.usable_upstream('10.1.2.3')

class NsHost(FakeHost):
    def run(self, argv, **kwargs):
        self.calls.append(argv)
        r = FakeResult()
        if argv[:3] == ['/usr/bin/nmcli', '-t', '-f'] and 'IP4.DNS' in argv:
            r.stdout = 'IP4.DNS[1]:127.0.0.53\nIP4.DNS[2]:10.9.0.1\nIP4.DNS[3]:fe80::1\nIP4.DNS[4]:10.9.0.1\n'
        return r
helper.HOST = NsHost()
try:
    assert helper.wan_nameservers() == ['10.9.0.1'], helper.wan_nameservers()
finally:
    helper.HOST = real_host

# Subnet overlap warning (WAN or eth0 vs the AP LAN)
orig_v4 = helper.ipv4_address
helper.ipv4_address = lambda iface: {'wlan0': '192.168.200.77/24', 'eth0': '192.168.199.5/24'}.get(iface)
try:
    overlaps = helper.subnet_overlaps()
finally:
    helper.ipv4_address = orig_v4
assert len(overlaps) == 1 and 'wlan0' in overlaps[0] and '192.168.200.0/24' in overlaps[0], overlaps

# Portal: no WAN default route -> unknown, no probe
orig_route = helper.route_status
helper.route_status = lambda: {}
try:
    assert helper.portal_status(force=True)['state'] == 'unknown'
finally:
    helper.route_status = orig_route

# tailscale_auth: empty key refused; key never on argv, passed by file
result = helper.action('tailscale_auth', {'action': 'tailscale_auth', 'confirm': True, 'authkey': '  '})
assert result['ok'] is False and result['error']['code'] == 'authkey_required', result
class AuthHost(FakeHost):
    def run(self, argv, **kwargs):
        self.calls.append(argv)
        return FakeResult()
auth_host = AuthHost()
helper.HOST = auth_host
try:
    helper.action('tailscale_auth', {'action': 'tailscale_auth', 'confirm': True, 'authkey': 'FIXTURE-authkey-123'})
finally:
    helper.HOST = real_host
login = [c for c in auth_host.calls if c[:2] == ['/usr/bin/tailscale', 'login']][0]
assert 'FIXTURE-authkey-123' not in ' '.join(login) and login[2].startswith('--auth-key=file:'), login

# set_ap_identity: byte-length SSID and ASCII passphrase
result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True, 'ssid': '\u00e9' * 20})
assert result['error']['code'] == 'invalid_ap_identity', result
result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True, 'passphrase': 'p\u00e4ssword123'})
assert result['error']['code'] == 'invalid_ap_identity', result

# SQM auto: env file set to yes, service restart, tuning timer restarted
sqm_host = FakeHost()
helper.HOST = sqm_host
try:
    result = helper.action('set_sqm_mode', {'action': 'set_sqm_mode', 'confirm': True, 'mode': 'auto'})
finally:
    helper.HOST = real_host
assert result['ok'] is True, result
assert ['/bin/systemctl', 'restart', helper.SQM_SERVICE] in sqm_host.calls, sqm_host.calls
assert ['/bin/systemctl', 'restart', 'travelpi-sqm-tune.timer'] in sqm_host.calls, sqm_host.calls

# DNS stack swap: drop-in written with the hotel nameserver, AdGuard stopped,
# Unbound restarted, mode file records the chosen front door.
dns_dir = tempfile.mkdtemp(prefix='travelpi-dns-')
orig_front, orig_mode = helper.UNBOUND_FRONT_CONF, helper.DNS_MODE_FILE
helper.UNBOUND_FRONT_CONF = dns_dir + '/front.conf'
helper.DNS_MODE_FILE = dns_dir + '/mode'
dns_host = FakeHost()
helper.HOST = dns_host
try:
    result = helper.action('set_dns_stack', {'action': 'set_dns_stack', 'confirm': True,
                                             'service': 'unbound', 'upstream': '172.20.0.1'})
finally:
    helper.HOST = real_host
    helper.UNBOUND_FRONT_CONF, helper.DNS_MODE_FILE = orig_front, orig_mode
assert result['ok'] is True, result
front = open(dns_dir + '/front.conf').read()
assert 'port: 53' in front and 'forward-addr: 172.20.0.1' in front, front
assert open(dns_dir + '/mode').read().strip() == 'TRAVELPI_DNS_MODE=unbound'
assert ['/usr/sbin/unbound-checkconf'] in dns_host.calls, dns_host.calls
assert ['/bin/systemctl', 'stop', 'adguardhome'] in dns_host.calls, dns_host.calls

# Status cache: repeat reads must hit the cache (page-load speed on relay paths)
import time as _time
first = helper.status_cached()
assert isinstance(first, dict), first
t0 = _time.monotonic()
second = helper.status_cached()
elapsed = _time.monotonic() - t0
assert second == first, 'cached status payload must match'
assert elapsed < 1.0, 'cache hit took %.2fs' % elapsed

# write_private_file: the helper runs as root and several targets live in /tmp,
# where any local user can plant a symlink. A planted link must be replaced,
# never written through, and the file must land private.
import os as _os
import tempfile as _tempfile

sandbox = _tempfile.mkdtemp(prefix='travelpi-write-test-')
victim = _os.path.join(sandbox, 'victim')
with open(victim, 'w') as handle:
    handle.write('PRE-EXISTING')
planted = _os.path.join(sandbox, 'planted.json')
_os.symlink(victim, planted)
helper.write_private_file(planted, '{"sentinel": "written"}', 0o600)
assert not _os.path.islink(planted), 'a planted symlink must be replaced, not followed'
assert open(victim).read() == 'PRE-EXISTING', 'write_private_file wrote through a planted symlink'
assert open(planted).read() == '{"sentinel": "written"}', open(planted).read()
assert _os.stat(planted).st_mode & 0o777 == 0o600, oct(_os.stat(planted).st_mode & 0o777)

# Persistence honesty: when the boot-time save fails, the action must say so
# instead of claiming the setting was saved for next boot.
real_writer = helper.write_private_file


def _failing_writer(path, content, mode=0o600):
    raise OSError('simulated read-only /etc')


helper.write_private_file = _failing_writer
governor_host = FakeHost()
helper.HOST = governor_host
try:
    result = helper.action('set_cpu_governor', {
        'action': 'set_cpu_governor', 'governor': 'ondemand', 'confirm': True,
    })
    assert result['ok'] is True, result
    assert 'this boot' in result['message'] and 'failed' in result['message'], result['message']

    result = helper.action('set_sqm_mode', {'action': 'set_sqm_mode', 'mode': 'off', 'confirm': True})
    assert result['ok'] is True, result
    assert 'failed' in result['message'], result['message']
finally:
    helper.write_private_file = real_writer
    helper.HOST = real_host

# And when the save succeeds, it must claim success without hedging. The
# boot-time file is redirected into a sandbox, as the DNS test does.
gov_ok_dir = _tempfile.mkdtemp(prefix='travelpi-gov-env-')
gov_ok_file = _os.path.join(gov_ok_dir, 'travelpi-power-profile')
real_profile_env = helper.POWER_PROFILE_ENV
helper.POWER_PROFILE_ENV = gov_ok_file
governor_ok = FakeHost()
helper.HOST = governor_ok
try:
    result = helper.action('set_cpu_governor', {
        'action': 'set_cpu_governor', 'governor': 'performance', 'confirm': True,
    })
finally:
    helper.HOST = real_host
    helper.POWER_PROFILE_ENV = real_profile_env
assert result['ok'] is True, result
assert 'saved for next boot' in result['message'] and 'failed' not in result['message'], result['message']
assert open(gov_ok_file).read().strip() == 'GOVERNOR=performance', open(gov_ok_file).read()
assert _os.stat(gov_ok_file).st_mode & 0o777 == 0o644, oct(_os.stat(gov_ok_file).st_mode & 0o777)

print('helper action contract checks passed')
