#!/usr/bin/env python3
"""Command-path coverage: the CLI subcommands and action success paths that the
other contracts leave unexercised.

tests/helper-contract.sh covers the invalid-command and unprivileged-action
gates; tests/helper-action-contract.py covers field validation and the
restart/wake/governor/reclaim/sqm/dns success paths. This file closes the rest:
the `scan` and `probe` CLI paths, and the vpn_toggle / tailscale_auth /
set_ap_radio / reset_radios success and rollback paths. Host commands run
through the helper's own HostAdapter seam, and the AP config is redirected into
a sandbox, so nothing here touches a real host.
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
HELPER = ROOT / 'helper' / 'travelpi-cockpit'
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


def cli(*args, stdin=''):
    proc = subprocess.run([sys.executable, str(HELPER), *args], input=stdin,
                          capture_output=True, text=True, timeout=120)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {'stdout': proc.stdout, 'stderr': proc.stderr}
    return proc.returncode, payload


# --- CLI: scan is root-only, and must refuse rather than reach for iw. The real
# subprocess path only refuses when the suite is unprivileged; the refusal is
# pinned independently of the suite's euid in tests/privilege-gate.py.
if os.geteuid() != 0:
    rc, payload = cli('scan')
    check(payload.get('error', {}).get('code') == 'not_privileged', f"scan must refuse unprivileged: {payload}")
    check(rc == 1, f"scan refusal must exit 1, got {rc}")

# --- CLI: probe must reject a malformed target, not silently probe the default.
rc, payload = cli('probe', 'not a host; rm -rf /')
check(payload.get('error', {}).get('code') == 'invalid_probe_target',
      f"probe must reject a malformed target: {payload}")
check(rc == 1, f"probe refusal must exit 1, got {rc}")

# --- CLI: probe with no target runs the probe path end to end.
rc, payload = cli('probe')
check(payload.get('ok') is True, f"probe must answer: {payload}")
check('probe' in payload and 'status' in payload.get('probe', {}),
      f"probe payload must nest a probe result: {payload}")
known_states = {'ASSOCIATION_FAILED', 'NO_DHCP', 'NO_ROUTE', 'CAPTIVE_PORTAL',
                'INTERNET_OK', 'INTERNET_BLOCKED', 'HTTPS_OK'}
state = payload.get('probe', {}).get('status')
check(state in known_states, f"probe status {state!r} is outside the probe_state enum")

# --- CLI: portal answers with a portal result (display-only hint).
rc, payload = cli('portal')
check(rc == 0, f"portal must exit 0, got {rc}")
check(payload.get('ok') is True, f"portal must answer: {payload}")
portal = payload.get('portal')
check(isinstance(portal, dict) and portal.get('state') in ('online', 'portal', 'blocked', 'unknown'),
      f"portal payload must nest a portal state: {payload}")

# --- Module-level action paths.
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)


class FakeResult:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = ''


class FakeHost:
    def __init__(self, fail_when=None):
        self.calls = []
        self.fail_when = fail_when

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.fail_when and self.fail_when(argv):
            return FakeResult(1)
        return FakeResult(0)


real_host = helper.HOST
try:
    # --- vpn_toggle: fixed unit mapping, both directions.
    host = FakeHost()
    helper.HOST = host
    result = helper.action('vpn_toggle', {'action': 'vpn_toggle', 'confirm': True,
                                          'provider': 'tailscale', 'enabled': True})
    check(result.get('ok') is True, f"vpn_toggle enable must apply: {result}")
    check(['/bin/systemctl', 'enable', '--now', 'tailscaled'] in host.calls, host.calls)

    host = FakeHost()
    helper.HOST = host
    result = helper.action('vpn_toggle', {'action': 'vpn_toggle', 'confirm': True,
                                          'provider': 'wireguard', 'enabled': False})
    check(['/bin/systemctl', 'disable', '--now', 'wg-quick@wg0'] in host.calls, host.calls)

    # openvpn is not a managed unit: the contract's provider set must be refused.
    result = helper.action('vpn_toggle', {'action': 'vpn_toggle', 'confirm': True,
                                          'provider': 'openvpn', 'enabled': True})
    check(result.get('error', {}).get('code') == 'invalid_vpn_request',
          f"openvpn must be refused: {result}")

    host = FakeHost(fail_when=lambda argv: 'systemctl' in ' '.join(argv))
    helper.HOST = host
    result = helper.action('vpn_toggle', {'action': 'vpn_toggle', 'confirm': True,
                                          'provider': 'tailscale', 'enabled': True})
    check(result.get('error', {}).get('code') == 'vpn_toggle_failed',
          f"vpn_toggle failure must be reported: {result}")

    # --- tailscale_auth: the authkey must never come back in the response.
    secret_key = 'FIXTURE-authkey-not-for-output'
    host = FakeHost()
    helper.HOST = host
    result = helper.action('tailscale_auth', {'action': 'tailscale_auth', 'confirm': True,
                                              'authkey': secret_key})
    check(result.get('ok') is True, f"tailscale_auth must acknowledge: {result}")
    check(secret_key not in json.dumps(result), "tailscale_auth echoed the authkey")
    check(any('tailscale' in ' '.join(call) and 'login' in ' '.join(call) for call in host.calls),
          f"tailscale_auth must start the login: {host.calls}")

    host = FakeHost()
    helper.HOST = host
    result = helper.action('tailscale_auth', {'action': 'tailscale_auth', 'confirm': True})
    check(result.get('ok') is False and result.get('error', {}).get('code') == 'authkey_required',
          f"tailscale_auth without a key must be refused: {result}")
    check(not any('login' in ' '.join(call) for call in host.calls),
          "an empty key must not run tailscale login")

    # --- set_ap_radio against a sandbox hostapd.conf: apply, and restore on failure.
    sandbox = tempfile.mkdtemp(prefix='travelpi-ap-test-')
    conf = Path(sandbox) / 'hostapd.conf'
    conf.write_text('interface=wlan1\nhw_mode=g\nchannel=6\nieee80211n=1\n'
                    'wmm_enabled=1\nieee80211ac=0\nieee80211ax=0\n')
    real_conf = helper.HOSTAPD
    helper.HOSTAPD = conf

    host = FakeHost()
    helper.HOST = host
    result = helper.action('set_ap_radio', {'action': 'set_ap_radio', 'confirm': True, 'band': '5ghz'})
    check(result.get('ok') is True, f"set_ap_radio must apply: {result}")
    applied = conf.read_text()
    check('hw_mode=a' in applied and 'channel=36' in applied and 'ieee80211ac=1' in applied,
          f"hostapd.conf must carry the 5 GHz profile: {applied}")
    check(['/bin/systemctl', 'restart', 'hostapd'] in host.calls, host.calls)

    # hostapd refuses to restart: the previous profile must come back, and the
    # refusal must name the restore.
    original = conf.read_text()
    host = FakeHost(fail_when=lambda argv: argv[:3] == ['/bin/systemctl', 'restart', 'hostapd'])
    helper.HOST = host
    result = helper.action('set_ap_radio', {'action': 'set_ap_radio', 'confirm': True, 'band': '2.4ghz'})
    check(result.get('error', {}).get('code') == 'ap_restart_failed',
          f"AP restart failure must be reported: {result}")
    check('restored' in result['error']['message'].lower(),
          f"the refusal must say the profile was restored: {result}")
    check(conf.read_text() == original,
          "hostapd.conf must be back to the previous profile after a failed restart")

    # --- connect_hotel: stale-profile handling and failure classification.
    class NmHost:
        def __init__(self, profiles, connect_rc=0, connect_err=''):
            self.profiles = [dict(p) for p in profiles]
            self.calls = []
            self.connect_rc = connect_rc
            self.connect_err = connect_err

        def run(self, argv, **kwargs):
            self.calls.append(list(argv))
            result = FakeResult(0)
            result.stderr = ''
            if argv[:5] == ['/usr/bin/nmcli', '-t', '-f', 'NAME,UUID,TYPE', 'connection']:
                result.stdout = ''.join('%s:%s:802-11-wireless\n' % (p['name'], p['uuid']) for p in self.profiles)
            elif argv[:4] == ['/usr/bin/nmcli', '-t', '-f', '802-11-wireless.ssid,connection.timestamp']:
                uuid = argv[-1]
                p = next(p for p in self.profiles if p['uuid'] == uuid)
                result.stdout = '802-11-wireless.ssid:%s\nconnection.timestamp:%s\n' % (p['ssid'], p['timestamp'])
            elif argv[:3] == ['/usr/bin/nmcli', '-t', '-f'] and 'NAME,DEVICE' in argv:
                result.stdout = ''
            elif argv[:5] == ['/usr/bin/nmcli', 'connection', 'delete', 'uuid', argv[-1]]:
                self.profiles = [p for p in self.profiles if p['uuid'] != argv[-1]]
            elif 'wifi' in argv and 'connect' in argv:
                if self.connect_rc:
                    result.returncode = self.connect_rc
                    result.stderr = self.connect_err
                    # NetworkManager leaves a profile behind when it fails.
                    if not any(p['ssid'] == 'HotelWiFi' for p in self.profiles):
                        self.profiles.append({'name': 'HotelWiFi', 'uuid': 'new-1', 'ssid': 'HotelWiFi', 'timestamp': 0})
            return result

        def deleted(self):
            return [c[-1] for c in self.calls if c[:4] == ['/usr/bin/nmcli', 'connection', 'delete', 'uuid']]

    real_probe = helper.probe
    helper.probe = lambda: {'status': 'INTERNET_OK'}
    real_status = helper.status
    helper.status = lambda: {'status': {}}
    request = {'action': 'connect_hotel', 'confirm': True, 'ssid': 'HotelWiFi', 'password': 'ExamplePass1'}
    stale = {'name': 'HotelWiFi', 'uuid': 'stale-1', 'ssid': 'HotelWiFi', 'timestamp': 0}
    used = {'name': 'HotelWiFi', 'uuid': 'used-1', 'ssid': 'HotelWiFi', 'timestamp': 1700000000}

    # stale (never activated) profile is deleted before the connect
    host = NmHost([stale])
    helper.HOST = host
    result = helper.action('connect_hotel', dict(request))
    check(result.get('ok') is True, f"connect must succeed: {result}")
    check(host.deleted() == ['stale-1'], host.calls)
    connect_index = next(i for i, c in enumerate(host.calls) if 'wifi' in c)
    delete_index = next(i for i, c in enumerate(host.calls) if c[-1] == 'stale-1' and 'delete' in c)
    check(delete_index < connect_index, "stale profile must be deleted before connecting")
    check(host.calls[connect_index][:3] == ['/usr/bin/nmcli', '-w', '30'], host.calls[connect_index])
    check('ExamplePass1' not in ' '.join(host.calls[connect_index]), "password must not be in argv")

    # a profile that has connected before stays authoritative
    host = NmHost([used])
    helper.HOST = host
    result = helper.action('connect_hotel', dict(request))
    check(result.get('ok') is True and host.deleted() == [], f"used profile must be untouched: {host.calls}")

    # wrong password on a used profile: classified, profile kept
    host = NmHost([used], connect_rc=4, connect_err='Error: Connection activation failed: (7) Secrets were required, but not provided.')
    helper.HOST = host
    result = helper.action('connect_hotel', dict(request))
    check(result.get('error', {}).get('code') == 'wrong_password', f"wrong password classification: {result}")
    check(result['error']['message'] == 'The network rejected the password; check it and try again.', result)
    check('used-1' not in host.deleted(), "a profile that connected before must survive a failed attempt")

    # failed attempt leaves no profile behind
    host = NmHost([], connect_rc=4, connect_err='Error: Connection activation failed: 4-way handshake failed')
    helper.HOST = host
    result = helper.action('connect_hotel', dict(request))
    check(result.get('error', {}).get('code') == 'wrong_password', result)
    check(host.profiles == [], f"failed attempt must not persist a profile: {host.profiles}")

    # blank password needing secrets, and unclassified failures
    host = NmHost([], connect_rc=4, connect_err='Secrets were required, but not provided')
    helper.HOST = host
    result = helper.action('connect_hotel', dict(request, password=''))
    check(result.get('error', {}).get('code') == 'password_required', result)
    host = NmHost([], connect_rc=10, connect_err='Error: No network with SSID found')
    helper.HOST = host
    result = helper.action('connect_hotel', dict(request))
    check(result.get('error', {}).get('code') == 'connect_failed', result)
    check('ExamplePass1' not in json.dumps(result), "password echoed")

    # hidden network: boolean flag adds `hidden yes`; non-boolean refused untouched
    host = NmHost([])
    helper.HOST = host
    result = helper.action('connect_hotel', dict(request, hidden=True))
    check(result.get('ok') is True, f"hidden connect must succeed: {result}")
    connect = next(c for c in host.calls if 'wifi' in c)
    check(connect[-2:] == ['hidden', 'yes'], connect)
    host = NmHost([])
    helper.HOST = host
    helper.action('connect_hotel', dict(request))
    check('hidden' not in next(c for c in host.calls if 'wifi' in c), "no hidden flag by default")
    host = NmHost([])
    helper.HOST = host
    result = helper.action('connect_hotel', dict(request, hidden='yes'))
    check(result.get('error', {}).get('code') == 'invalid_hidden', result)
    check(not host.calls, "invalid hidden must not touch the host")

    helper.probe = real_probe
    helper.status = real_status
    helper.HOST = real_host

    helper.HOSTAPD = real_conf
    helper.HOST = real_host

    # A host with no hostapd.conf must refuse before any restart.
    helper.HOSTAPD = Path(sandbox) / 'missing.conf'
    host = FakeHost()
    helper.HOST = host
    result = helper.action('set_ap_radio', {'action': 'set_ap_radio', 'confirm': True, 'band': '5ghz'})
    check(result.get('error', {}).get('code') == 'hostapd_config_missing',
          f"missing hostapd.conf must refuse: {result}")
    check(not host.calls, f"no host command may run after the refusal: {host.calls}")

    # --- set_ap_radio channel control: validated against what the radio reports.
    real_caps = helper.ap_phy_capabilities
    helper.ap_phy_capabilities = lambda: {
        'bands': ['2.4ghz', '5ghz', '6ghz'], 'capabilities': ['ap', 'wifi6e'],
        'supported_channels': {'2.4ghz': [1, 6, 11], '5ghz': [36, 40, 149], '6ghz': [1, 5, 37]},
    }
    conf.write_text('interface=wlan1\nhw_mode=g\nchannel=6\nieee80211n=1\n'
                    'wmm_enabled=1\nieee80211ac=0\nieee80211ax=0\n')
    helper.HOSTAPD = conf
    host = FakeHost()
    helper.HOST = host
    result = helper.action('set_ap_radio', {'action': 'set_ap_radio', 'confirm': True,
                                            'band': '5ghz', 'channel': 149})
    check(result.get('ok') is True, f"a hardware-supported channel must apply: {result}")
    applied = conf.read_text()
    check('channel=149' in applied, f"hostapd.conf must carry the chosen channel: {applied}")

    host2 = FakeHost()
    helper.HOST = host2
    result = helper.action('set_ap_radio', {'action': 'set_ap_radio', 'confirm': True,
                                            'band': '5ghz', 'channel': 120})
    check(result.get('error', {}).get('code') == 'invalid_ap_channel',
          f"an unsupported/DFS channel must be refused: {result}")
    check(not any('restart' in ' '.join(c) for c in host2.calls),
          "the channel refusal must not restart hostapd")

    result = helper.action('set_ap_radio', {'action': 'set_ap_radio', 'confirm': True, 'band': '6ghz'})
    check(result.get('ok') is True, f"6 GHz with proven channels must apply: {result}")
    applied = conf.read_text()
    check('he_6ghz=1' in applied and 'ieee80211ax=1' in applied and 'hw_mode=a' in applied,
          f"6 GHz profile needs ax + he_6ghz: {applied}")

    # 6 GHz without host evidence: honest unavailable, and nothing changes.
    helper.ap_phy_capabilities = lambda: {'bands': ['2.4ghz'], 'capabilities': [],
                                          'supported_channels': {'2.4ghz': [1, 6]}}
    before = conf.read_text()
    host2 = FakeHost()
    helper.HOST = host2
    result = helper.action('set_ap_radio', {'action': 'set_ap_radio', 'confirm': True, 'band': '6ghz'})
    check(result.get('error', {}).get('code') == 'radio_capability_missing',
          f"6 GHz needs host evidence: {result}")
    check(conf.read_text() == before, "the 6 GHz refusal must not touch hostapd.conf")
    check(not host2.calls, f"the 6 GHz refusal must not touch the host: {host2.calls}")
    helper.ap_phy_capabilities = real_caps

    # --- set_ap_identity: name/password change with restore-on-fail and
    # secret hygiene (the passphrase never appears in a response).
    conf.write_text('interface=wlan1\nssid=TravelPi\nwpa=2\nwpa_key_mgmt=WPA-PSK\n'
                    'wpa_passphrase=oldpassphrase1\nhw_mode=a\nchannel=36\nieee80211n=1\n'
                    'wmm_enabled=1\nieee80211ac=1\nieee80211ax=1\n')
    helper.HOSTAPD = conf
    host3 = FakeHost()
    helper.HOST = host3
    new_secret = 'brand-new-secret-2026'
    result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True,
                                               'ssid': 'Camp Van', 'passphrase': new_secret})
    check(result.get('ok') is True, f"set_ap_identity must apply: {result}")
    applied = conf.read_text()
    check('ssid=Camp Van' in applied and new_secret in applied and 'wpa=2' in applied,
          f"hostapd.conf must carry the new identity: {applied}")
    check(new_secret not in json.dumps(result), "the response must never echo the passphrase")

    result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True,
                                               'passphrase': 'short'})
    check(result.get('error', {}).get('code') == 'invalid_ap_identity',
          f"a short passphrase must be refused: {result}")

    result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True})
    check(result.get('error', {}).get('code') == 'invalid_ap_identity',
          f"an empty identity request must be refused: {result}")

    result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True,
                                               'ssid': 'bad\nname=1'})
    check(result.get('error', {}).get('code') == 'invalid_ap_identity',
          f"control characters in the SSID must be refused (conf injection): {result}")

    result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True,
                                               'passphrase': ' leading space'})
    check(result.get('error', {}).get('code') == 'invalid_ap_identity',
          f"a leading-space passphrase must be refused (hostapd strips it): {result}")
    result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True,
                                               'passphrase': '"quoted-secret"'})
    check(result.get('error', {}).get('code') == 'invalid_ap_identity',
          f"a quoted passphrase must be refused (hostapd C-style quoting): {result}")

    original = conf.read_text()
    host4 = FakeHost(fail_when=lambda argv: argv[:3] == ['/bin/systemctl', 'restart', 'hostapd'])
    helper.HOST = host4
    result = helper.action('set_ap_identity', {'action': 'set_ap_identity', 'confirm': True,
                                               'ssid': 'Broken Name'})
    check(result.get('error', {}).get('code') == 'ap_identity_failed',
          f"AP identity restart failure must be reported: {result}")
    check('restored' in result['error']['message'].lower(),
          f"the refusal must say the identity was restored: {result}")
    check(conf.read_text() == original,
          "hostapd.conf must be back to the previous identity after a failed restart")

    # --- portal cache semantics: the dashboard poll reuses the cache;
    # force=True (the `portal fresh` CLI) must bypass it and re-probe.
    real_portal_cache = helper.PORTAL_CACHE
    portal_cache_file = Path(sandbox) / 'portal-cache.json'
    helper.PORTAL_CACHE = str(portal_cache_file)
    import time as _time
    real_route_status = helper.route_status
    helper.route_status = lambda: {'gateway': '10.0.0.1', 'interface': 'wlan0'}
    portal_cache_file.write_text(json.dumps({'ts': _time.monotonic() - 10, 'state': 'online',
                                             'portal_url': None}))
    portal_cache_file.chmod(0o644)
    untrusted = helper.portal_status()
    check(untrusted.get('state') == 'unknown' and untrusted.get('age_s') == 0,
          f"a cache file that is not mode 0600 must be ignored and recomputed: {untrusted}")
    portal_cache_file.write_text(json.dumps({'ts': _time.monotonic() - 10, 'state': 'online',
                                             'portal_url': None}))
    portal_cache_file.chmod(0o600)
    cached = helper.portal_status()
    check(cached.get('state') == 'online' and cached.get('age_s', -1) >= 0,
          f"a fresh cache must be served: {cached}")
    host5 = FakeHost()  # empty stdout -> probe answers 'unknown'
    helper.HOST = host5
    forced = helper.portal_status(force=True)
    check(forced.get('state') == 'unknown',
          f"force=True must bypass the cache and re-probe: {forced}")
    helper.PORTAL_CACHE = real_portal_cache
    helper.route_status = real_route_status

    # --- reset_radios: needs two radios; a host reporting fewer must be refused.
    real_radios = helper.wifi_radio_interfaces
    helper.wifi_radio_interfaces = lambda: []
    host = FakeHost()
    helper.HOST = host
    result = helper.action('reset_radios', {'action': 'reset_radios', 'confirm': True})
    check(result.get('error', {}).get('code') == 'reset_radios_failed',
          f"reset_radios must refuse with one radio missing: {result}")
    check(not host.calls, f"reset_radios refusal must not touch services: {host.calls}")
    helper.wifi_radio_interfaces = real_radios

    # --- cake_rate: the unit reads TRAVELPI_SQM_RATE from EnvironmentFile, and an
    # EnvironmentFile overrides `systemctl set-environment`, so the rate file
    # must be written before the restart, and the applied qdisc rate must be
    # verified before the action claims the rate is set.
    sqm_dir = tempfile.mkdtemp(prefix='travelpi-sqm-rate-')
    sqm_env = Path(sqm_dir) / 'travelpi-sqm'
    sqm_env.write_text('TRAVELPI_SQM_RATE=20Mbit\n')
    real_env = helper.SQM_ENV_FILE
    real_cake_status = helper.cake_status
    real_service_state = helper.service_state
    helper.SQM_ENV_FILE = sqm_env
    helper.cake_status = lambda: {'rate': '20Mbit', 'state': 'active'}
    helper.service_state = lambda unit: 'active'

    def healthy_status(rate):
        return {'defaultRoute': {'interface': helper.WAN}, 'cake': {'state': 'active', 'rate': rate}}

    class OrderingHost(FakeHost):
        """Records what the unit's EnvironmentFile actually contains at the
        moment `systemctl restart` runs, which is what the unit will read."""

        def __init__(self, env_file):
            super().__init__()
            self.env_file = env_file
            self.env_at_restart = []

        def run(self, argv, **kwargs):
            if argv[:2] == ['/bin/systemctl', 'restart']:
                self.env_at_restart.append(Path(self.env_file).read_text())
            return super().run(argv, **kwargs)

    real_status = helper.status
    host = OrderingHost(sqm_env)
    helper.HOST = host
    helper.status = lambda: {'ok': True, 'status': healthy_status('13Mbit')}
    try:
        result = helper.action('set_cake_rate', {'action': 'set_cake_rate', 'confirm': True,
                                                 'rate_kbit': 13000})
    finally:
        helper.status = real_status
    check(result.get('ok') is True, f"cake_rate must apply: {result}")
    check('set to 13000 kbit/s' in result.get('message', ''), result.get('message'))
    check('TRAVELPI_SQM_RATE=13000kbit' in sqm_env.read_text(),
          f"the rate file must carry the new rate: {sqm_env.read_text()}")
    check(not any('set-environment' in ' '.join(call) for call in host.calls),
          f"set-environment is overridden by EnvironmentFile and must not be used: {host.calls}")
    check(host.env_at_restart and 'TRAVELPI_SQM_RATE=13000kbit' in host.env_at_restart[0],
          f"the file the unit reads at restart must already hold the new rate: {host.env_at_restart}")

    # A healthy qdisc at the wrong rate must be reported as such, not as success.
    sqm_env.write_text('TRAVELPI_SQM_RATE=20Mbit\n')
    host = FakeHost()
    helper.HOST = host
    helper.status = lambda: {'ok': True, 'status': healthy_status('20Mbit')}
    try:
        result = helper.action('set_cake_rate', {'action': 'set_cake_rate', 'confirm': True,
                                                 'rate_kbit': 13000})
    finally:
        helper.status = real_status
    check(result.get('ok') is True, f"cake_rate must answer: {result}")
    message = result.get('message', '')
    check('saved for the next CAKE restart' in message, f"unverified rate must be reported honestly: {message}")
    check('set to 13000' not in message, f"must not claim the rate was set: {message}")

    # A failed restart must restore the previous rate into the file.
    sqm_env.write_text('TRAVELPI_SQM_RATE=20Mbit\n')
    host = FakeHost(fail_when=lambda argv: argv[:2] == ['/bin/systemctl', 'restart'])
    helper.HOST = host
    result = helper.action('set_cake_rate', {'action': 'set_cake_rate', 'confirm': True,
                                             'rate_kbit': 13000})
    check(result.get('error', {}).get('code') == 'cake_restart_failed', f"restart failure must be reported: {result}")
    check('20Mbit' in sqm_env.read_text(), f"previous rate must come back into the file: {sqm_env.read_text()}")

    # The whole env file (incl. TRAVELPI_SQM_AUTOTUNE) comes back, not a rewrite.
    original_env = 'TRAVELPI_SQM_RATE=20Mbit\nTRAVELPI_SQM_AUTOTUNE=yes\n# keep me\n'
    sqm_env.write_text(original_env)
    helper.HOST = FakeHost(fail_when=lambda argv: argv[:2] == ['/bin/systemctl', 'restart'])
    result = helper.action('set_cake_rate', {'action': 'set_cake_rate', 'confirm': True, 'rate_kbit': 13000})
    check(result.get('error', {}).get('code') == 'cake_restart_failed', result)
    check(sqm_env.read_text() == original_env, f"env file must be restored verbatim: {sqm_env.read_text()!r}")

    # CAKE inactive before (no previous rate): a failed apply must not leave
    # the new rate persisted.
    helper.cake_status = lambda: {'rate': None, 'state': 'inactive'}
    sqm_env.write_text(original_env)
    result = helper.action('set_cake_rate', {'action': 'set_cake_rate', 'confirm': True, 'rate_kbit': 13000})
    check(result.get('ok') is False and '13000' not in sqm_env.read_text(),
          f"failed apply with no previous rate must not leave the new rate: {sqm_env.read_text()!r}")
    sqm_env.unlink()
    result = helper.action('set_cake_rate', {'action': 'set_cake_rate', 'confirm': True, 'rate_kbit': 13000})
    check(result.get('ok') is False and not sqm_env.exists(),
          "a failed first-time apply must not leave an env file behind")

    helper.SQM_ENV_FILE = real_env
    helper.cake_status = real_cake_status
    helper.service_state = real_service_state
    helper.status = real_status

    # --- set_sqm_mode off: qdisc removal is claimed only when it is verified.
    real_status = helper.status
    host = FakeHost()
    helper.HOST = host
    helper.status = lambda: {'ok': True, 'status': {'cake': {'state': 'active'}}}
    try:
        result = helper.action('set_sqm_mode', {'action': 'set_sqm_mode', 'mode': 'off', 'confirm': True})
    finally:
        helper.status = real_status
    check('still reported active' in result.get('message', ''),
          f"an active qdisc after stop must not be reported as removed: {result}")

    helper.status = lambda: {'ok': True, 'status': {'cake': {'state': 'inactive'}}}
    try:
        result = helper.action('set_sqm_mode', {'action': 'set_sqm_mode', 'mode': 'off', 'confirm': True})
    finally:
        helper.status = real_status
    check('qdisc is removed' in result.get('message', ''),
          f"a verified inactive qdisc must be reported as removed: {result}")

    # --- set_dns_stack (unbound): a persistence failure must be reported.
    real_writer = helper.write_private_file

    def failing_writer(path, content, mode=0o600):
        raise OSError('simulated read-only /etc')

    helper.write_private_file = failing_writer
    host = FakeHost()
    helper.HOST = host
    helper.UNBOUND_FRONT_CONF = Path(tempfile.mkdtemp(prefix='travelpi-dns-')) / 'front.conf'
    helper.DNS_MODE_FILE = helper.UNBOUND_FRONT_CONF.parent / 'mode'
    try:
        result = helper.action('set_dns_stack', {'action': 'set_dns_stack',
                                                 'service': 'unbound', 'upstream': '172.20.0.1',
                                                 'confirm': True})
    finally:
        helper.write_private_file = real_writer
        helper.HOST = real_host
    check(result.get('ok') is True, f"unbound mode must apply: {result}")
    check('failed' in result.get('message', ''),
          f"unbound persistence failure must be reported: {result}")
finally:
    helper.HOST = real_host

# --- WAN probe: a hotel portal that redirects (302/200) to a private address
# is CAPTIVE_PORTAL, not INTERNET_OK; a public redirect and a plain 200 stay OK.
real_parts = (helper.parse_link, helper.ipv4_address, helper.route_status_for, helper.fixed_http_probe)
helper.parse_link = lambda iface: {'ssid': 'Hotel'}
helper.ipv4_address = lambda iface: '10.1.1.5'
helper.route_status_for = lambda iface: {'interface': iface, 'gateway': '10.1.1.1'}
try:
    for status_code, redirect, expected in (
            (302, 'http://192.168.50.1/login', 'CAPTIVE_PORTAL'),
            (200, 'http://10.0.0.1/portal', 'CAPTIVE_PORTAL'),
            (511, '', 'CAPTIVE_PORTAL'),
            (302, 'http://www.google.com/', 'INTERNET_OK'),
            (200, '', 'INTERNET_OK')):
        helper.fixed_http_probe = lambda target, c=status_code, r=redirect: {
            'http_status': c, 'redirect_url': r, 'returncode': 0, 'duration_ms': 1}
        got = helper.probe()['status']
        check(got == expected, f"probe {status_code} -> {redirect!r} must be {expected}, got {got}")
finally:
    helper.parse_link, helper.ipv4_address, helper.route_status_for, helper.fixed_http_probe = real_parts

# fixed_http_probe parses "code redirect_url" from curl (curl stdout stubbed).
class CurlHost:
    def __init__(self, out):
        self.out = out

    def run(self, argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, self.out, '')


real_host2 = helper.HOST
try:
    helper.HOST = CurlHost('302 http://172.16.0.1/x')
    parsed = helper.fixed_http_probe('google.com')
    check(parsed['http_status'] == 302 and parsed['redirect_url'] == 'http://172.16.0.1/x', parsed)
    helper.HOST = CurlHost('200 ')
    parsed = helper.fixed_http_probe('google.com')
    check(parsed['http_status'] == 200 and parsed['redirect_url'] == '', parsed)
finally:
    helper.HOST = real_host2

# --- /tmp caches: only a regular 0600 file owned by us/root, not a symlink,
# with the required keys is believed.
cache_dir = Path(tempfile.mkdtemp(prefix='travelpi-cache-'))
good = cache_dir / 'good.json'
good.write_text(json.dumps({'a': 1}))
good.chmod(0o600)
check(helper.read_private_cache(str(good), ('a',)) == {'a': 1}, 'a trusted cache must be read')
check(helper.read_private_cache(str(good), ('a', 'b')) is None, 'missing required keys must be ignored')
good.chmod(0o644)
check(helper.read_private_cache(str(good), ('a',)) is None, 'a non-0600 cache must be ignored')
good.chmod(0o600)
link = cache_dir / 'link.json'
link.symlink_to(good)
check(helper.read_private_cache(str(link), ('a',)) is None, 'a symlinked cache must be ignored')
bad = cache_dir / 'bad.json'
bad.write_text('[1, 2]')
bad.chmod(0o600)
check(helper.read_private_cache(str(bad), ()) is None, 'a non-object cache must be ignored')
check(helper.read_private_cache(str(cache_dir / 'absent.json'), ()) is None, 'a missing cache is None')
# Freshness uses the monotonic clock with its own stamp; a future stamp is expired.
stamped = cache_dir / 'stamped.json'
helper.store_cache(str(stamped), payload={'x': 1})
check(helper.fresh_cache(str(stamped), ('payload',), 30) is not None, 'a just-written cache is fresh')
check(helper.fresh_cache(str(stamped), ('payload',), -1) is None, 'ttl exceeded is not fresh')
stamped.write_text(json.dumps({'_cached_at': helper.time.monotonic() + 9999, 'payload': {}}))
stamped.chmod(0o600)
check(helper.fresh_cache(str(stamped), ('payload',), 30) is None, 'a future stamp must count as expired')
# Wall-clock mtime must not matter: an ancient mtime on a fresh stamp is still fresh.
helper.store_cache(str(stamped), payload={'x': 1})
os.utime(stamped, (1, 1))
check(helper.fresh_cache(str(stamped), ('payload',), 30) is not None, 'mtime (wall clock) must not age a cache')

# Portal redirect heuristic (table).
for url, probe_host, expected, label in [
    ('http://10.20.30.1/login', 'neverssl.com', True, 'private IPv4'),
    ('http://100.64.3.2:8080/x', 'neverssl.com', True, 'CGNAT IPv4 with port'),
    ('http://[fd12:3456::1]/portal', 'neverssl.com', True, 'bracketed IPv6 ULA'),
    ('http://user:pw@10.0.0.1/', 'neverssl.com', True, 'userinfo with private IPv4'),
    ('http://8.8.8.8/', 'neverssl.com', False, 'public IPv4'),
    ('http://www.google.com/', 'google.com', False, 'hostname, same registrable domain'),
    ('https://google.com/', 'google.com', False, 'scheme upgrade'),
    ('http://portal.hotel.example/login', 'google.com', True, 'hostname, different domain'),
    ('http://portal.hotel.example/login', '8.8.8.8', False, 'IP probe host: no hostname heuristic'),
    ('http://[::1', 'google.com', False, 'malformed URL'),
    ('', 'google.com', False, 'empty'),
    (None, 'google.com', False, 'None'),
]:
    check(helper.redirects_to_private_address(url, probe_host) is expected, 'redirect heuristic: ' + label)
check(helper.redirects_to_private_address('http://10.1.1.1/') is True, 'private IPv4 needs no probe host')

# Caches are per euid so root and the unprivileged helper never collide.
for name in ('STATUS_CACHE', 'PORTAL_CACHE', 'JOURNAL_EVENTS_CACHE', 'TAILSCALE_STATUS_CACHE'):
    check('travelpi-%d-' % os.geteuid() in getattr(helper, name), name + ' must carry the euid')

if failures:
    print("helper command paths FAILED:")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print("helper command paths checks passed")
