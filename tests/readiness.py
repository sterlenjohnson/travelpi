#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import os
from pathlib import Path

path = Path(__file__).parents[1] / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

scan = helper.parse_wifi_scan(
    'BSS aa:bb:cc:dd:ee:01(on wlan0)\n'
    '\tfreq: 2412\n\tcapability: ESS Privacy ShortSlotTime (0x0411)\n'
    '\tsignal: -72.00 dBm\n\tSSID: weak\n'
    '\tRSN:\t * Version: 1\n\t\t * Group cipher: CCMP\n'
    '\t\t * Authentication suites: PSK SAE\n'
    'BSS aa:bb:cc:dd:ee:02(on wlan0)\n'
    '\tfreq: 5955\n\tcapability: ESS ShortSlotTime (0x0401)\n'
    '\tsignal: -48.00 dBm\n\tSSID: strong-6e\n'
    'BSS aa:bb:cc:dd:ee:03(on wlan0)\n'
    '\tfreq: 5180\n\tSignal: -58 dBm\n\tSSID: CapsSignal\n'
    '\tWPA:\t * Version: 1\n\t\t * Authentication suites: 802.1X\n'
    'BSS aa:bb:cc:dd:ee:04(on wlan0)\n'
    '\tfreq: 2437\n\tcapability: ESS Privacy (0x0011)\n'
    '\tsignal: -80.00 dBm\n\tSSID: wep-legacy\n'
)
# 6 GHz channel = (freq - 5950) / 5: 5955 -> 1, 5975 -> 5, 6135 -> 37, 7115 -> 233.
for freq, channel in ((5955, 1), (5975, 5), (6135, 37), (7115, 233)):
    scanned = helper.parse_wifi_scan('BSS aa:bb:cc:dd:ee:09(on wlan0)\n\tfreq: %d\n\tsignal: -50.00 dBm\n\tSSID: six\n' % freq)
    assert scanned[0]['channel'] == channel and scanned[0]['band'] == '6ghz', (freq, scanned)
for freq, channel in ((2412, 1), (2484, 14), (5180, 36), (5745, 149)):
    scanned = helper.parse_wifi_scan('BSS aa:bb:cc:dd:ee:09(on wlan0)\n\tfreq: %d\n\tsignal: -50.00 dBm\n\tSSID: x\n' % freq)
    assert scanned[0]['channel'] == channel, (freq, scanned)
by_ssid = {item['ssid']: item for item in scan}
assert [item['ssid'] for item in scan] == ['strong-6e', 'CapsSignal', 'weak', 'wep-legacy']
assert scan[0]['band'] == '6ghz'
assert scan[0]['channel'] == 1
assert by_ssid['strong-6e']['security'] == 'open'
assert by_ssid['weak']['security'] == 'secured', by_ssid['weak']
assert by_ssid['weak']['auth'] == ['PSK', 'SAE'], by_ssid['weak']
assert by_ssid['CapsSignal']['security'] == 'secured'
assert by_ssid['CapsSignal']['auth'] == ['802.1X']
assert by_ssid['wep-legacy']['security'] == 'secured'
assert '_privacy' not in by_ssid['weak']
# iw dev scan prints "Signal:" capitalized; ranking must use it, not -999.
assert by_ssid['CapsSignal']['signal_dbm'] == -58.0

readiness = helper.readiness_status()
assert readiness['wifi_scan']['interface'] == 'wlan0'
assert readiness['wifi_scan']['automatic'] is False
assert readiness['role_switch']['available'] is False
assert readiness['transient_networkmanager']['available'] is False
assert readiness['ap_profiles']['all_bands'] is False
assert readiness['firmware']['state'] in ('ok', 'elevated', 'unknown')
if readiness['firmware']['state'] == 'elevated':
    assert isinstance(readiness['firmware']['overrides'], list) and readiness['firmware']['overrides']
if readiness['firmware']['state'] == 'ok':
    assert readiness['firmware']['overrides'] == []
guards = readiness['memory_guards']
assert set(guards['guarded_units']) | set(guards['unprotected_units']) == set(helper.RESOURCE_GUARD_DROPINS)
assert not (set(guards['guarded_units']) & set(guards['unprotected_units']))
print('readiness checks passed')

# A hung or busy radio is a failed scan, never an empty neighbourhood.
import subprocess

class ScanHost:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    def run(self, argv, **kwargs):
        self.calls += 1
        code, out = self.results.pop(0)
        return subprocess.CompletedProcess(argv, code, out, '')

_real_host, _real_sleep = helper.HOST, helper.time.sleep
helper.time.sleep = lambda seconds: None
helper.pressure_status = lambda: {'pressured': False}
try:
    helper.HOST = ScanHost([(124, ''), (124, '')])
    response = helper.wifi_scan()
    assert response['ok'] is False and response['error']['code'] == 'scan_timeout', response
    helper.HOST = ScanHost([(240, ''), (240, '')])
    assert helper.wifi_scan()['error']['code'] == 'scan_busy'
    helper.HOST = ScanHost([(124, ''), (0, 'BSS aa:bb:cc:dd:ee:01(on wlan0)\n\tfreq: 2437\n\tsignal: -40.00 dBm\n\tSSID: Retry\n\tRSN:\t * Version: 1\n')])
    response = helper.wifi_scan()
    assert response['ok'] and response['networks'][0]['ssid'] == 'Retry' and response['networks'][0]['security'] == 'secured'
    assert helper.HOST.calls == 2
finally:
    helper.HOST, helper.time.sleep = _real_host, _real_sleep

# DNS status: the upstream_dns block decides the mode, and a running AdGuard
# whose lookups fail is 'degraded', not 'inactive'.
yaml = "dns:\n  upstream_dns:\n    - '[/home.example/]100.64.0.9'\n    - 172.20.0.1\n  upstream_dns_file: \"\"\n  fallback_dns:\n    - 127.0.0.1:5335\n"
assert helper.adguard_upstreams(yaml) == ['[/home.example/]100.64.0.9', '172.20.0.1']
helper.ADGUARD_CONFIG = Path('/nonexistent-travelpi-adguard.yaml')
helper.text = lambda argv, **kwargs: yaml if argv[:2] == ['sudo', '/bin/cat'] else ''
helper.dns_stack_mode = lambda: 'adguard'
for running, resolving, expected in ((True, True, 'active'), (True, False, 'degraded'), (False, False, 'inactive')):
    helper.process_active = lambda name, r=running: r
    helper.dns_responder_live = lambda v=resolving: v
    status = helper.adguard_dns_status()
    assert status['service'] == expected, (running, resolving, status)
    assert status['mode'] == 'wan-dns' and status['upstream'] == 'Hotel WAN DNS (Unbound fallback)', status
print('scan timeout and DNS degraded checks passed')

# IPv6 state: only a real global unicast address (2000::/3) counts as global;
# the ULA on the AP is not a delegated prefix.
ULA_AP = 'inet6 fd12:3456:789a:1::1/64 scope global'
GUA_WAN = 'inet6 2001:db8:1:2:3:4:5:6/64 scope global dynamic'
def ip6_host(wan, ap, route):
    def fake(argv, **kwargs):
        if argv[:3] == ['/sbin/ip', '-6', '-o']:
            return ap if argv[6] == helper.LAN else wan
        if argv[:3] == ['/sbin/ip', '-6', 'route']:
            return route
        return ''
    return fake
import tempfile as _tf
_dir = Path(_tf.mkdtemp())
_ula = _dir / 'ula-prefix'
_ula.write_text('fd12:3456:789a:1::/64\n')
helper.ULA_PREFIX_FILE = str(_ula)
helper.AP_RA_OFF_DROPIN = '/nonexistent-travelpi-ra-off.conf'
helper.AP_NETWORK_FILE = str(_dir / '070-travelpi-ap.network')
Path(helper.AP_NETWORK_FILE).write_text('[Match]\nName=wlan1\n')
helper.service_state = lambda unit: 'active'
helper.text = ip6_host(GUA_WAN, ULA_AP, 'default via fe80::1 dev wlan0')
state = helper.ipv6_status()
assert state['state'] == 'ula-only' and state['wan_global'] is True and state['ap_global'] is False, state
assert 'no global prefix is delegated' in state['detail'], state
assert 'radvd' not in state, state
# ADR 0007: the PD client does not exist, so a GUA on the AP is reported as a
# fact but delegation ('active') is never claimed.
helper.text = ip6_host(GUA_WAN, 'inet6 2001:db8:9:9::1/64 scope global', 'default via fe80::1 dev wlan0')
state = helper.ipv6_status()
assert state['state'] == 'ula-only' and state['ap_global'] is True, state
helper.text = ip6_host('', ULA_AP, '')
state = helper.ipv6_status()
assert state['state'] == 'ula-only' and state['wan_global'] is False, state
# RAs are live only with systemd-networkd active and the installed profile.
helper.service_state = lambda unit: 'inactive'
state = helper.ipv6_status()
assert state['state'] == 'off' and 'systemd-networkd' in state['detail'], state
helper.service_state = lambda unit: 'active'
os.rename(helper.AP_NETWORK_FILE, helper.AP_NETWORK_FILE + '.gone')
assert helper.ipv6_status()['state'] == 'off'
os.rename(helper.AP_NETWORK_FILE + '.gone', helper.AP_NETWORK_FILE)
assert helper.ipv6_status()['state'] == 'ula-only'
# The ra-off drop-in stops advertisements.
_ra_off = _dir / 'ra-off.conf'
_ra_off.write_text('[Network]\nIPv6SendRA=no\n')
helper.AP_RA_OFF_DROPIN = str(_ra_off)
state = helper.ipv6_status()
assert state['state'] == 'off' and 'stopped' in state['detail'], state
helper.AP_RA_OFF_DROPIN = '/nonexistent-travelpi-ra-off.conf'
# No ULA configured and nothing on the AP: honest 'off', never a ULA claim.
helper.ULA_PREFIX_FILE = str(_ula) + '.missing'
helper.text = ip6_host('', '', '')
state = helper.ipv6_status()
assert state['state'] == 'off' and 'No ULA prefix is configured' in state['detail'], state
print('ipv6 gua-vs-ula checks passed')
