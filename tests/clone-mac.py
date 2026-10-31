#!/usr/bin/env python3
"""WAN MAC identity change (apply_mac_clone): behavior through the HOST seam.

Pins what tests/wan-band.py does not: validate_mac's rejection table and
normalisation, an unreadable current setting refusing before anything is
changed, a failed reconnect restoring the original cloned-mac value, the
*_unrestored codes when the restore itself fails, and that no failure path
claims the identity was applied. Generic identifiers only.
"""
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

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
    def __init__(self, returncode=0, stdout=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ''


class MacHost:
    """Stateful nmcli stub: tracks the profile's cloned-mac setting."""

    def __init__(self, original='02:aa:bb:cc:dd:01', up_results=(), modify_results=(),
                 read_rc=0, read_raises=False, active='HotelWiFi:wlan0'):
        self.setting = original
        self.up_results = list(up_results)        # per `connection up`: returncode
        self.modify_results = list(modify_results)  # per `connection modify`: returncode
        self.read_rc = read_rc
        self.read_raises = read_raises
        self.active = active
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:3] == ['/usr/bin/nmcli', 'connection', 'modify']:
            rc = self.modify_results.pop(0) if self.modify_results else 0
            if rc == 0:
                self.setting = argv[5]
            return Result(rc)
        if argv[:3] == ['/usr/bin/nmcli', 'connection', 'up']:
            return Result(self.up_results.pop(0) if self.up_results else 0)
        if argv[:2] == ['/usr/bin/nmcli', '-g'] and argv[2] == helper.MAC_SETTING:
            if self.read_raises:
                raise OSError('nmcli vanished')
            if self.read_rc:
                return Result(self.read_rc, '')
            return Result(0, self.setting.replace(':', '\\:') + '\n')
        if argv[:2] == ['/usr/bin/nmcli', '-t']:
            return Result(0, self.active)
        return Result(0)

    def verbs(self):
        return [c[2] for c in self.calls if c[:2] == ['/usr/bin/nmcli', 'connection']]


def act(host, **request):
    helper.HOST = host
    return helper.action('apply_mac_clone', {'action': 'apply_mac_clone', 'confirm': True, **request})


# --- validate_mac: accepted and rejected forms.
check(helper.validate_mac('02:AA:BB:CC:DD:01') == '02:aa:bb:cc:dd:01', 'uppercase input is normalised to lowercase')
check(helper.validate_mac('06:00:00:00:00:01') == '06:00:00:00:00:01', 'any unicast locally administered MAC is accepted')
for bad, why in (('01:aa:bb:cc:dd:01', 'multicast bit set'),
                 ('03:aa:bb:cc:dd:01', 'multicast and local bits'),
                 ('00:00:00:00:00:00', 'all zero'),
                 ('00:aa:bb:cc:dd:01', 'universally administered (burned-in style)'),
                 ('02:aa:bb:cc:dd', 'too short'),
                 ('02:aa:bb:cc:dd:01:02', 'too long'),
                 ('02-aa-bb-cc-dd-01', 'wrong separator'),
                 ('02:aa:bb:cc:dd:0g', 'non-hex digit'),
                 ('02:aa:bb:cc:dd:01\n', 'trailing newline'),
                 ('', 'empty'), (None, 'None')):
    try:
        helper.validate_mac(bad)
        check(False, 'validate_mac must reject %r (%s)' % (bad, why))
    except ValueError:
        pass

real_host, real_status, real_probe = helper.HOST, helper.status, helper.probe
helper.status = lambda: {'ok': True, 'status': {'marker': 'fresh'}}
helper.probe = lambda *a, **k: {'status': 'INTERNET_OK'}
try:
    # --- the action refuses invalid MACs before touching the host.
    for bad in ('01:aa:bb:cc:dd:01', '00:00:00:00:00:00', 'nonsense', ''):
        host = MacHost()
        result = act(host, mac=bad)
        check(result.get('error', {}).get('code') == 'invalid_mac', 'invalid mac %r must be refused: %s' % (bad, result))
        check(not any(c[:3] == ['/usr/bin/nmcli', 'connection', 'modify'] for c in host.calls),
              'an invalid mac must not reach nmcli modify')
    host = MacHost()
    result = act(host)  # mode defaults to specific, and no MAC given
    check(result.get('error', {}).get('code') == 'invalid_mac', 'specific mode without a MAC must be refused: %s' % result)

    # --- success: uppercase is normalised on the way into NetworkManager.
    host = MacHost()
    result = act(host, mac='02:AA:BB:CC:DD:99')
    check(result.get('ok') is True and host.setting == '02:aa:bb:cc:dd:99', 'uppercase MAC must apply normalised: %s %s' % (result, host.setting))
    check(host.verbs() == ['modify', 'down', 'up'], 'apply order must be modify, down, up: %s' % host.verbs())

    # --- success per mode, with distinct honest messages.
    for request, expected, phrase in (({'mac': '02:11:22:33:44:55'}, '02:11:22:33:44:55', 'clone applied'),
                                      ({'mode': 'random'}, 'random', 'randomized'),
                                      ({'mode': 'default'}, '', 'hardware default')):
        host = MacHost()
        result = act(host, **request)
        check(result.get('ok') is True and host.setting == expected, 'mode %s must apply: %s' % (request, result))
        check(phrase in result.get('message', ''), 'mode %s message must say %r: %s' % (request, phrase, result))
        check(result.get('action') == 'apply_mac_clone', 'success must name the action')

    # --- a verified connection with no internet is applied, but says so.
    helper.probe = lambda *a, **k: {'status': 'NO_INTERNET'}
    result = act(MacHost(), mac='02:11:22:33:44:55')
    check(result.get('ok') is True and 'no internet' in result.get('message', ''), 'NO_INTERNET must be reported honestly: %s' % result)
    helper.probe = lambda *a, **k: {'status': 'INTERNET_OK'}

    # --- not connected: nothing changes.
    host = MacHost(active='')
    result = act(host, mac='02:11:22:33:44:55')
    check(result.get('error', {}).get('code') == 'wan_not_connected', 'no active WAN must refuse: %s' % result)
    check(host.verbs() == [], 'no WAN profile must not run any connection verb')

    # --- initial read failures: nothing may change, and the code is mac_update_failed.
    for label, host in (('read raises', MacHost(read_raises=True)), ('read exits nonzero', MacHost(read_rc=1))):
        for request in ({'mac': '02:11:22:33:44:55'}, {'mode': 'random'}, {'mode': 'default'}):
            host2 = MacHost(read_raises=host.read_raises, read_rc=host.read_rc)
            result = act(host2, **request)
            check(result.get('ok') is False and result['error']['code'] == 'mac_update_failed',
                  '%s (%s) must refuse with mac_update_failed: %s' % (label, request, result))
            check(host2.verbs() == [] and host2.setting == '02:aa:bb:cc:dd:01',
                  '%s (%s) must change nothing: %s' % (label, request, host2.verbs()))

    # --- modify itself fails: nothing changed, update code per mode.
    for request, code in (({'mac': '02:11:22:33:44:55'}, 'mac_update_failed'),
                          ({'mode': 'random'}, 'mac_update_failed'),
                          ({'mode': 'default'}, 'mac_update_failed')):
        host = MacHost(modify_results=[1])
        result = act(host, **request)
        check(result.get('error', {}).get('code') == code, 'modify failure %s: %s' % (request, result))
        check(host.verbs() == ['modify'] and host.setting == '02:aa:bb:cc:dd:01', 'a failed modify must stop there: %s' % host.verbs())

    # --- reconnect fails, restore works: original value back, failure reported.
    for request, code in (({'mac': '02:11:22:33:44:55'}, 'wan_reconnect_failed'),
                          ({'mode': 'random'}, 'mac_verify_failed'),
                          ({'mode': 'default'}, 'mac_verify_failed')):
        host = MacHost(original='02:aa:bb:cc:dd:01', up_results=[1])  # first up fails, restore-up works
        result = act(host, **request)
        check(result.get('ok') is False and result['error']['code'] == code, 'reconnect failure %s: %s' % (request, result))
        check(host.setting == '02:aa:bb:cc:dd:01', 'the original cloned-mac must be restored: %s' % host.setting)
        check('status' not in result and 'applied' not in result['error']['message'].lower().replace('restored', ''),
              'a failed change must not claim it was applied: %s' % result)
        check(host.verbs() == ['modify', 'down', 'up', 'modify', 'down', 'up'], 'restore must modify, down, up: %s' % host.verbs())

    # --- original was empty (hardware default): the restore writes the empty value back.
    host = MacHost(original='', up_results=[1])
    result = act(host, mac='02:11:22:33:44:55')
    check(result['error']['code'] == 'wan_reconnect_failed' and host.setting == '', 'an empty original must be restored as empty: %s' % host.setting)

    # --- restore also fails (reconnect, or the modify itself): *_unrestored.
    for request, code in (({'mac': '02:11:22:33:44:55'}, 'wan_reconnect_failed_unrestored'),
                          ({'mode': 'random'}, 'mac_verify_failed_unrestored'),
                          ({'mode': 'default'}, 'mac_verify_failed_unrestored')):
        result = act(MacHost(up_results=[1, 1]), **request)
        check(result.get('error', {}).get('code') == code, 'restore reconnect failure %s: %s' % (request, result))
        check('could not be brought back' in result['error']['message'], 'the unrestored message must say so: %s' % result)
        host = MacHost(up_results=[1], modify_results=[0, 1])  # restore-modify fails
        result = act(host, **request)
        check(result.get('error', {}).get('code') == code, 'restore modify failure %s: %s' % (request, result))
        check(host.setting == request.get('mac', request.get('mode') == 'random' and 'random' or ''),
              'when the restore modify fails the new value stays, and that is what is reported')

    # --- probe verification failure (connection up OK, but no WAN) restores too.
    helper.probe = lambda *a, **k: {'status': 'NO_ROUTE'}
    host = MacHost()
    result = act(host, mac='02:11:22:33:44:55')
    check(result['error']['code'] == 'wan_reconnect_failed' and host.setting == '02:aa:bb:cc:dd:01',
          'a failed probe must restore the original identity: %s %s' % (result, host.setting))
    # --- ensure_wan_spoof: a failed read is not "unset"; a real clone is never overwritten.
    for label, host in (('nonzero exit', MacHost(read_rc=1)), ('exception', MacHost(read_raises=True))):
        helper.HOST = host
        helper.ensure_wan_spoof('HotelWiFi')
        check(not any(c[:3] == ['/usr/bin/nmcli', 'connection', 'modify'] for c in host.calls),
              'ensure_wan_spoof must not modify the profile when the read fails (%s): %s' % (label, host.calls))
    host = MacHost(original='02:aa:bb:cc:dd:01')
    helper.HOST = host
    helper.ensure_wan_spoof('HotelWiFi')
    check(host.setting == '02:aa:bb:cc:dd:01', 'a real clone must be kept')
    host = MacHost(original='permanent')
    helper.HOST = host
    helper.ensure_wan_spoof('HotelWiFi')
    check(host.setting == 'random', 'an unset (permanent) clone becomes random: %s' % host.setting)

    # --- nmcli -t escapes ':' in names; profile names with a colon round-trip.
    check(helper.split_terse('Hotel\\: Lobby:wlan0') == ['Hotel: Lobby', 'wlan0'], 'split_terse must unescape colons')
    helper.HOST = MacHost(active='Hotel\\: Lobby:wlan0')
    check(helper.active_profile('wlan0') == 'Hotel: Lobby', 'active_profile must unescape a colon in the name: %r' % helper.active_profile('wlan0'))
    check(helper.active_profile('wlan9') is None, 'other interface -> None')
finally:
    helper.HOST, helper.status, helper.probe = real_host, real_status, real_probe

if failures:
    print('clone mac FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('clone mac checks passed')
