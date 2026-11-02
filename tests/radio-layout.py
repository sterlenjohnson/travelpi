#!/usr/bin/env python3
"""Radio role layout end to end: apply_radio_layout through wan_flip and
reset_radios, with the HOST seam stubbed and hostapd/dnsmasq configs in a
sandbox (helper.HOSTAPD and helper.DNSMASQ_CONF are redirected).

Pins: the success path rewrites both config owners and re-points the WAN
profile; a hostapd that will not come up rolls back hostapd.conf AND the
dnsmasq conf and leaves the NetworkManager profiles untouched; a restore that
itself fails is reported as *_unrestored; one radio is refused before any
mutation; and wan_flip stays honestly unavailable until readiness proves a
role swap (ADR 0002/0004). The stubbed-available readiness below exists only
so the layout path can be driven; it does not make the swap reachable.
"""
import importlib.machinery
import importlib.util
import json
import os
import stat
import sys
import tempfile
import time
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


HOSTAPD_TEXT = ('interface=wlan1\nssid=TravelPi\nhw_mode=a\nchannel=36\nieee80211n=1\n'
                'ieee80211ac=1\nieee80211ax=1\nwpa=2\n')
DNSMASQ_TEXT = 'interface=wlan1\ndhcp-range=192.0.2.10,192.0.2.100,12h\n'


class Result:
    def __init__(self, returncode=0, stdout=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ''


class RadioHost:
    def __init__(self, hostapd, dnsmasq, radios=('wlan0', 'wlan1'), hostapd_active=True,
                 sabotage_backup=None):
        self.hostapd, self.dnsmasq = hostapd, dnsmasq
        self.radios = list(radios)
        self.hostapd_active = hostapd_active
        self.sabotage_backup = sabotage_backup  # Path deleted when is-active runs (backup lost)
        self.cloned_mac = 'permanent'
        self.link_local = True
        self.calls = []
        self.conf_at_restart = []  # (hostapd.conf, dnsmasq.conf) at each hostapd restart

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:2] == ['/bin/systemctl', 'restart'] and argv[2] == 'hostapd':
            self.conf_at_restart.append((self.hostapd.read_text(), self.dnsmasq.read_text()))
        if argv[:3] == ['/bin/systemctl', 'is-active', 'hostapd']:
            if self.sabotage_backup is not None:
                self.sabotage_backup.unlink()
            return Result(0 if self.hostapd_active else 3)
        if argv[:5] == ['/usr/bin/nmcli', '-t', '-f', 'DEVICE,TYPE', 'device']:
            return Result(0, ''.join(r + ':wifi\n' for r in self.radios) + 'eth0:ethernet\n')
        if argv[:5] == ['/usr/bin/nmcli', '-t', '-f', 'NAME,TYPE', 'connection'] and '--active' not in argv:
            return Result(0, 'HotelWiFi:802-11-wireless\nWired:802-3-ethernet\n')
        if '--active' in argv and 'NAME,TYPE' in argv:
            return Result(0, 'HotelWiFi:802-11-wireless\n')
        # `nmcli -g` prints the bare value; `-t -f` would print "field:value".
        if argv[:3] == ['/usr/bin/nmcli', '-g', 'connection.interface-name']:
            return Result(0, 'wlan0\n')
        if argv[:3] == ['/usr/bin/nmcli', '-g', '802-11-wireless.cloned-mac-address']:
            return Result(0, self.cloned_mac + '\n')
        if argv[:5] == ['/sbin/ip', '-6', 'addr', 'show', 'dev']:
            return Result(0, 'inet6 fe80::1/64 scope link\n' if self.link_local else '')
        if argv[:2] == ['/usr/sbin/sysctl', '-qw'] and argv[2].endswith('disable_ipv6=0'):
            self.link_local = True  # the enable edge regenerates the link-local address
        return Result(0)

    def index(self, *prefix):
        for i, call in enumerate(self.calls):
            if call[:len(prefix)] == list(prefix):
                return i
        return -1

    def mutated_nm(self):
        return [c for c in self.calls if c[:3] in (['/usr/bin/nmcli', 'connection', 'modify'],
                                                     ['/usr/bin/nmcli', 'connection', 'up'])]


sandbox = Path(_mkdtemp(prefix='travelpi-radio-layout-'))
hostapd_conf = sandbox / 'hostapd.conf'
dnsmasq_conf = sandbox / 'travelpi.conf'
ula_file = sandbox / 'ula-prefix'
ula_file.write_text('fd12:3456:789a:1::/64\n')

saved = (helper.HOST, helper.HOSTAPD, helper.DNSMASQ_CONF, helper.status, helper.interface_hardware,
         helper.readiness_status, helper.ULA_PREFIX_FILE, time.sleep)
helper.HOSTAPD = hostapd_conf
helper.DNSMASQ_CONF = dnsmasq_conf
helper.ULA_PREFIX_FILE = str(ula_file)
helper.status = lambda: {'ok': True, 'status': {'marker': 'fresh'}}
helper.interface_hardware = lambda iface: {'bands': ['2.4ghz', '5ghz'] if iface == 'wlan1' else ['2.4ghz']}
time.sleep = lambda seconds: None  # the layout waits 3 s for hostapd; do not wait here


def reset_files():
    hostapd_conf.write_text(HOSTAPD_TEXT)
    dnsmasq_conf.write_text(DNSMASQ_TEXT)
    for stale in sandbox.glob('*.travelpi-backup'):
        stale.unlink()


def act(name, host):
    helper.HOST = host
    return helper.action(name, {'action': name, 'confirm': True})


try:
    # --- wan_flip is unavailable by default: honest refusal, host untouched.
    reset_files()
    helper.readiness_status = saved[5]
    host = RadioHost(hostapd_conf, dnsmasq_conf)
    result = act('wan_flip', host)
    check(result.get('error', {}).get('code') == 'unavailable', 'wan_flip must stay unavailable without role-swap evidence: %s' % result)
    check(all(c[0] == '/sbin/ip' and 'show' in c for c in host.calls),
          'the unavailable refusal may only read state, never mutate: %s' % host.calls)
    check(hostapd_conf.read_text() == HOSTAPD_TEXT and dnsmasq_conf.read_text() == DNSMASQ_TEXT, 'the refusal must not touch the configs')
    check(helper.readiness_status()['role_switch']['available'] is False, 'readiness must not advertise a reachable role swap')

    # From here the layout path is driven with the gate opened by the stub.
    helper.readiness_status = lambda: {'role_switch': {'available': True, 'reason': ''}}

    # --- a flushed radio has no link-local: it is regenerated before the gateway is added.

    # --- wan_flip success: both owners move to the new radio, WAN profile follows.
    reset_files()
    host = RadioHost(hostapd_conf, dnsmasq_conf)
    result = act('wan_flip', host)
    check(result.get('ok') is True and result.get('status') == {'marker': 'fresh'}, 'wan_flip must succeed: %s' % result)
    check('Radio roles swapped' in result.get('message', ''), 'success message: %s' % result)
    check('interface=wlan0' in hostapd_conf.read_text() and 'interface=wlan1' not in hostapd_conf.read_text(),
          'hostapd.conf must move to the new AP radio: %s' % hostapd_conf.read_text())
    check('interface=wlan0' in dnsmasq_conf.read_text() and 'dhcp-range=192.0.2.10' in dnsmasq_conf.read_text(),
          'dnsmasq conf must follow and keep its other lines: %s' % dnsmasq_conf.read_text())
    check('hw_mode=g' in hostapd_conf.read_text() and 'channel=6' in hostapd_conf.read_text()
          and 'ieee80211ac=0' in hostapd_conf.read_text(), '2.4 GHz-only new AP radio must get the g/6 profile')
    check(host.index('/bin/systemctl', 'stop', 'hostapd') < host.index('/bin/systemctl', 'restart', 'hostapd'),
          'hostapd must be stopped before the layout is applied')
    check(host.conf_at_restart and host.conf_at_restart[0][0].startswith('interface=wlan0'),
          'hostapd must restart against the new config')
    check(['/sbin/ip', '-4', 'addr', 'flush', 'dev', 'wlan0'] in host.calls, 'the AP address flush must be IPv4-scoped')
    check(not any(c[:3] == ['/sbin/ip', 'addr', 'flush'] or c[:4] == ['/sbin/ip', '-6', 'addr', 'flush'] for c in host.calls),
          'the apply path must never flush IPv6 (link-local loss, 2026-10-30)')
    check(['/sbin/ip', '-6', 'addr', 'add', 'fd12:3456:789a:1::1/64', 'dev', 'wlan0'] in host.calls,
          'the ULA gateway must be re-added on the new AP radio')
    check(['/bin/systemctl', 'restart', 'systemd-networkd'] in host.calls, 'networkd must be restarted so it re-advertises on the new radio')
    check(host.index('/bin/systemctl', 'restart', 'systemd-networkd') > host.index('/sbin/ip', '-6', 'addr', 'add'),
          'networkd restarts after the AP addresses are in place')
    check(not any(c[:2] == ['/usr/sbin/sysctl', '-qw'] for c in host.calls), 'an existing link-local must not be toggled')
    check(['/usr/bin/nmcli', 'connection', 'modify', 'HotelWiFi', 'connection.interface-name', 'wlan1'] in host.calls,
          'the WAN profile must be re-pointed at the old AP radio')
    check(any(c[:4] == ['/usr/bin/nmcli', 'connection', 'up', 'HotelWiFi'] for c in host.calls), 'the WAN profile must be brought up')
    check(['/usr/bin/nmcli', 'connection', 'modify', 'HotelWiFi', '802-11-wireless.cloned-mac-address', 'random'] in host.calls,
          'a WAN profile on the permanent MAC must be randomised before it moves radios')

    # --- an existing cloned MAC identity is kept, not overwritten.
    reset_files()
    host = RadioHost(hostapd_conf, dnsmasq_conf)
    host.cloned_mac = '02:aa:bb:cc:dd:01'
    act('wan_flip', host)
    check(not any(c[:3] == ['/usr/bin/nmcli', 'connection', 'modify'] and '802-11-wireless.cloned-mac-address' in c for c in host.calls),
          'an existing cloned MAC identity must be kept, not overwritten')

    # --- a flushed radio has no link-local: it is regenerated before the gateway is added.
    reset_files()
    host = RadioHost(hostapd_conf, dnsmasq_conf)
    host.link_local = False
    result = act('wan_flip', host)
    check(result.get('ok') is True, 'a missing link-local must be recovered, not fatal: %s' % result)
    toggle_down = host.index('/usr/sbin/sysctl', '-qw', 'net.ipv6.conf.wlan0.disable_ipv6=1')
    toggle_up = host.index('/usr/sbin/sysctl', '-qw', 'net.ipv6.conf.wlan0.disable_ipv6=0')
    check(0 <= toggle_down < toggle_up < host.index('/sbin/ip', '-6', 'addr', 'add'),
          'link-local must be toggled back before the gateway add: %s' % host.calls)

    # --- hostapd will not start: BOTH configs roll back, NM is not modified.
    reset_files()
    host = RadioHost(hostapd_conf, dnsmasq_conf, hostapd_active=False)
    result = act('wan_flip', host)
    check(result.get('error', {}).get('code') == 'ap_restart_failed', 'a dead hostapd must be reported: %s' % result)
    check('restored' in result.get('error', {}).get('message', '').lower(), 'the failure must say the config was restored: %s' % result)
    check(hostapd_conf.read_text() == HOSTAPD_TEXT, 'hostapd.conf must roll back: %s' % hostapd_conf.read_text())
    check(dnsmasq_conf.read_text() == DNSMASQ_TEXT, 'dnsmasq conf must roll back with hostapd: %s' % dnsmasq_conf.read_text())
    check(host.mutated_nm() == [], 'a rolled-back layout must not modify or bring up NM connections: %s' % host.mutated_nm())
    check('status' not in result, 'a failed layout must not carry a success status')
    restarts = [c for c in host.calls if c[:2] == ['/bin/systemctl', 'restart']]
    check([c[2] for c in restarts].count('hostapd') == 2 and [c[2] for c in restarts].count('dnsmasq') == 2,
          'both services must be restarted again on the restored config: %s' % restarts)
    check(host.conf_at_restart[-1] == (HOSTAPD_TEXT, DNSMASQ_TEXT), 'the final restart must run on the original configs')
    check([c for c in host.calls if c == ['/bin/systemctl', 'restart', 'systemd-networkd']].__len__() == 2,
          'networkd must be restarted on the failed apply and again on the restore path')
    check(['/sbin/ip', '-4', 'addr', 'flush', 'dev', 'wlan0'] in host.calls[host.index('/bin/systemctl', 'is-active', 'hostapd'):],
          'the abandoned radio must lose the AP addresses on rollback')

    # --- the restore itself fails (a backup is gone): *_unrestored, no success claim.
    reset_files()
    lost = dnsmasq_conf.with_suffix('.conf.travelpi-backup')
    host = RadioHost(hostapd_conf, dnsmasq_conf, hostapd_active=False, sabotage_backup=lost)
    result = act('wan_flip', host)
    check(result.get('error', {}).get('code') == 'ap_restart_failed_unrestored', 'a failed restore must be *_unrestored: %s' % result)
    check(str(lost) in result['error']['message'] and 'restored' not in result['error']['message'].replace('could not be restored', ''),
          'the unrestored message must name the backup and not claim a restore: %s' % result)
    check(host.mutated_nm() == [], 'an unrestored failure must not touch NM connections')

    # --- hostapd.conf carries the AP passphrase: 0600 and the backup gone after success.
    reset_files()
    hostapd_conf.chmod(0o644)
    host = RadioHost(hostapd_conf, dnsmasq_conf)
    result = act('wan_flip', host)
    check(result.get('ok') is True, 'layout must succeed for the mode check: %s' % result)
    check(stat.S_IMODE(hostapd_conf.stat().st_mode) == 0o600, 'hostapd.conf must be 0600 after the layout, got %o' % stat.S_IMODE(hostapd_conf.stat().st_mode))
    check(not hostapd_conf.with_suffix('.conf.travelpi-backup').exists(), 'the hostapd backup must be removed after success')

    # --- rollback restores hostapd.conf at 0600 and removes the backup.
    reset_files()
    hostapd_conf.chmod(0o644)
    host = RadioHost(hostapd_conf, dnsmasq_conf, hostapd_active=False)
    result = act('wan_flip', host)
    check(result.get('error', {}).get('code') == 'ap_restart_failed', 'rollback expected: %s' % result)
    check(hostapd_conf.read_text() == HOSTAPD_TEXT and stat.S_IMODE(hostapd_conf.stat().st_mode) == 0o600,
          'a restored hostapd.conf must be 0600')
    check(not hostapd_conf.with_suffix('.conf.travelpi-backup').exists(), 'the hostapd backup must be removed after a restore')

    # --- an exception after the rewrite restores both configs instead of failing in place.
    reset_files()
    host = RadioHost(hostapd_conf, dnsmasq_conf)
    real_run = host.run

    def boom(argv, **kwargs):
        if argv[:3] == ['/bin/systemctl', 'stop', 'hostapd']:
            raise RuntimeError('host exploded')
        return real_run(argv, **kwargs)
    host.run = boom
    result = act('wan_flip', host)
    check(result.get('error', {}).get('code') == 'ap_restart_failed', 'an exception after the rewrite must roll back: %s' % result)
    check(hostapd_conf.read_text() == HOSTAPD_TEXT and dnsmasq_conf.read_text() == DNSMASQ_TEXT,
          'an exception after the rewrite must restore both configs')

    # --- one radio: refused before any mutation.
    reset_files()
    host = RadioHost(hostapd_conf, dnsmasq_conf, radios=('wlan1',))
    result = act('wan_flip', host)
    check(result.get('error', {}).get('code') == 'wan_flip_failed', 'one radio must refuse wan_flip: %s' % result)
    check(hostapd_conf.read_text() == HOSTAPD_TEXT and dnsmasq_conf.read_text() == DNSMASQ_TEXT, 'one-radio refusal must leave configs alone')
    check(not any(c[:2] in (['/bin/systemctl', 'stop'], ['/bin/systemctl', 'restart']) for c in host.calls),
          'one-radio refusal must not stop or restart services')
    host = RadioHost(hostapd_conf, dnsmasq_conf, radios=('wlan1',))
    result = act('reset_radios', host)
    check(result.get('error', {}).get('code') == 'reset_radios_failed', 'one radio must refuse reset_radios: %s' % result)
    check(host.mutated_nm() == [] and not any(c[0] == '/bin/systemctl' and c[1] != 'is-active' for c in host.calls), 'reset_radios refusal must not mutate')

    # --- missing configs refuse before any teardown.
    reset_files()
    dnsmasq_conf.unlink()
    host = RadioHost(hostapd_conf, dnsmasq_conf)
    result = act('reset_radios', host)
    check(result.get('error', {}).get('code') == 'dnsmasq_config_missing', 'a missing dnsmasq conf must refuse: %s' % result)
    check(hostapd_conf.read_text() == HOSTAPD_TEXT and not any(c[:2] == ['/bin/systemctl', 'stop'] for c in host.calls),
          'a missing dnsmasq conf must refuse before any teardown')

    # --- reset_radios: AP goes on the 5 GHz-capable radio, success and rollback.
    reset_files()
    hostapd_conf.write_text(HOSTAPD_TEXT.replace('interface=wlan1', 'interface=wlan0'))
    dnsmasq_conf.write_text(DNSMASQ_TEXT.replace('wlan1', 'wlan0'))
    host = RadioHost(hostapd_conf, dnsmasq_conf)
    result = act('reset_radios', host)
    check(result.get('ok') is True and 'AP on wlan1, WAN on wlan0' in result.get('message', ''), 'reset_radios must pick the 5 GHz radio: %s' % result)
    check('interface=wlan1' in hostapd_conf.read_text() and 'hw_mode=a' in hostapd_conf.read_text(), '5 GHz profile for the AP radio')
    check(['/usr/bin/nmcli', 'connection', 'modify', 'HotelWiFi', 'connection.interface-name', 'wlan0'] in host.calls,
          'the WAN profile must be bound to the other radio')

    reset_files()
    hostapd_conf.write_text(HOSTAPD_TEXT.replace('interface=wlan1', 'interface=wlan0'))
    dnsmasq_conf.write_text(DNSMASQ_TEXT.replace('wlan1', 'wlan0'))
    before = (hostapd_conf.read_text(), dnsmasq_conf.read_text())
    host = RadioHost(hostapd_conf, dnsmasq_conf, hostapd_active=False)
    result = act('reset_radios', host)
    check(result.get('error', {}).get('code') == 'ap_restart_failed', 'reset_radios must report a dead hostapd: %s' % result)
    check((hostapd_conf.read_text(), dnsmasq_conf.read_text()) == before, 'reset_radios must roll back both configs')
    check(host.mutated_nm() == [], 'reset_radios rollback must not touch NM connections')
    check(json.dumps(result).count('ok') >= 0, 'result stays serialisable')
finally:
    (helper.HOST, helper.HOSTAPD, helper.DNSMASQ_CONF, helper.status, helper.interface_hardware,
     helper.readiness_status, helper.ULA_PREFIX_FILE, time.sleep) = saved

if failures:
    print('radio layout FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('radio layout checks passed')
