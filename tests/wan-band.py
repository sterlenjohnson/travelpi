#!/usr/bin/env python3
"""Radio band inventory (wlan0/wlan1) and the set_wan_band action, with
stubbed iw/nmcli output. No host is contacted."""
import importlib.machinery
import importlib.util
import tempfile
from pathlib import Path

path = Path(__file__).parents[1] / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

IW_24_ONLY = '''
    Band 1:
        * 2412.0 MHz [1] (20.0 dBm)
        * 2437.0 MHz [6] (20.0 dBm)
'''
IW_24_5 = IW_24_ONLY + '''
    Band 2:
        * 5180.0 MHz [36] (17.0 dBm)
        * 5520.0 MHz [104] (24.0 dBm) (no IR, radar detection)
        * 5745.0 MHz [149] (disabled)
'''
IW_24_5_6 = IW_24_5 + '''
    Band 4:
        * 5955.0 MHz [1] (23.0 dBm)
'''
IW_5_DISABLED = '''
    Band 1:
        * 2412.0 MHz [1] (disabled)
    Band 2:
        * 5180.0 MHz [36] (17.0 dBm)
'''

assert helper.parse_radio_capabilities(IW_24_ONLY)['bands'] == ['2.4ghz']
assert helper.parse_radio_capabilities(IW_24_5)['bands'] == ['2.4ghz', '5ghz']
assert helper.parse_radio_capabilities(IW_24_5_6)['bands'] == ['2.4ghz', '5ghz', '6ghz']
# A band with only disabled frequencies is not offered.
assert helper.parse_radio_capabilities(IW_5_DISABLED)['bands'] == ['5ghz']
assert helper.band_for_frequency(2437) == '2.4ghz'
assert helper.band_for_frequency(5180) == '5ghz'
assert helper.band_for_frequency(6135) == '6ghz'
assert helper.band_for_frequency(None) is None


class Result:
    def __init__(self, returncode=0, stdout=''):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ''


class FakeHost:
    def __init__(self, iw, band='', active='HotelWiFi:wlan0', up_fail=0, probe_status='INTERNET_OK'):
        self.iw = iw  # phy name -> iw text
        self.band = band
        self.active = active
        self.up_fail = up_fail  # number of `connection up` calls that fail
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:3] == ['/sbin/iw', 'phy', argv[2]] and argv[3:] == ['info']:
            return Result(0, self.iw.get(argv[2], ''))
        if argv[:2] == ['/usr/bin/nmcli', '-t']:
            return Result(0, self.active)
        if argv[:2] == ['/usr/bin/nmcli', '-g'] and argv[2] == '802-11-wireless.band':
            return Result(0, self.band + '\n')
        if argv[:3] == ['/usr/bin/nmcli', 'connection', 'modify']:
            self.band = argv[5]
            return Result(0)
        if argv[:3] == ['/usr/bin/nmcli', 'connection', 'up']:
            if self.up_fail:
                self.up_fail -= 1
                return Result(1)
            return Result(0)
        return Result(0)

    def modifies(self):
        return [c for c in self.calls if c[:3] == ['/usr/bin/nmcli', 'connection', 'modify']]


def make_sys(root, radios):
    for interface, phy in radios.items():
        directory = Path(root) / interface / 'phy80211'
        directory.mkdir(parents=True)
        (directory / 'name').write_text(phy + '\n')


real_host, real_sys, real_probe = helper.HOST, helper.DEVICE_SYS, helper.probe
helper.probe = lambda *a, **k: {'status': 'INTERNET_OK'}
try:
    with tempfile.TemporaryDirectory() as tmp:
        # wlan0 = 2.4 + 5, wlan1 = 2.4 + 5 + 6
        make_sys(tmp, {'wlan0': 'phy0', 'wlan1': 'phy1'})
        helper.DEVICE_SYS = Path(tmp)
        helper.HOST = FakeHost({'phy0': IW_24_5, 'phy1': IW_24_5_6})
        assert helper.interface_hardware('wlan0')['bands'] == ['2.4ghz', '5ghz']
        assert helper.interface_hardware('wlan1')['bands'] == ['2.4ghz', '5ghz', '6ghz']

        # 2.4-only WAN radio
        helper.HOST = FakeHost({'phy0': IW_24_ONLY, 'phy1': IW_24_5})
        assert helper.interface_hardware('wlan0')['bands'] == ['2.4ghz']

        # absent radio
        absent = helper.interface_hardware('wlan9')
        assert absent['present'] is False and absent['bands'] == []

        # --- set_wan_band ---
        def act(host, band, **extra):
            helper.HOST = host
            request = {'action': 'set_wan_band', 'band': band, 'confirm': True}
            request.update(extra)
            return helper.action('set_wan_band', request)

        iw = {'phy0': IW_24_5, 'phy1': IW_24_5_6}

        host = FakeHost(iw, band='')
        result = act(host, '5ghz')
        assert result['ok'] is True, result
        assert host.band == 'a'
        assert ['/usr/bin/nmcli', 'connection', 'modify', 'HotelWiFi', '802-11-wireless.band', 'a'] in host.calls

        host = FakeHost(iw, band='a')
        result = act(host, '2.4ghz')
        assert result['ok'] is True and host.band == 'bg', result

        host = FakeHost(iw, band='bg')
        result = act(host, 'auto')
        assert result['ok'] is True and host.band == '', result

        # refusals
        host = FakeHost(iw, active='')
        assert act(host, '5ghz')['error']['code'] == 'wan_not_connected'
        assert host.modifies() == []

        host = FakeHost({'phy0': IW_24_ONLY}, band='')
        assert act(host, '5ghz')['error']['code'] == 'band_unsupported'
        assert host.modifies() == []

        host = FakeHost({}, band='')
        assert act(host, '5ghz')['error']['code'] == 'band_unsupported'

        # 6 GHz: not reported -> band_unsupported; reported -> NM cannot select it
        host = FakeHost(iw)
        assert act(host, '6ghz')['error']['code'] == 'band_unsupported'
        host = FakeHost({'phy0': IW_24_5_6})
        refusal = act(host, '6ghz')
        assert refusal['error']['code'] == 'radio_capability_missing', refusal
        assert host.modifies() == []

        host = FakeHost(iw)
        assert act(host, '7ghz')['error']['code'] == 'invalid_wan_band'
        assert helper.action('set_wan_band', {'action': 'set_wan_band', 'band': '5ghz'})['error']['code'] == 'confirmation_required'
        assert act(FakeHost(iw), '5ghz', interface='wlan1')['error']['code'] == 'unknown_fields'

        # restore on reconnect failure: previous band written back
        host = FakeHost(iw, band='bg', up_fail=1)
        result = act(host, '5ghz')
        assert result['ok'] is False and result['error']['code'] == 'wan_band_failed', result
        assert host.band == 'bg', 'previous band must be restored'
        assert len(host.modifies()) == 2

        # restore on failed verification
        helper.probe = lambda *a, **k: {'status': 'WAN_DOWN'}
        host = FakeHost(iw, band='')
        result = act(host, '5ghz')
        assert result['ok'] is False and host.band == '', result
        # restore also fails -> honest unrestored code
        host = FakeHost(iw, band='bg', up_fail=2)
        result = act(host, '5ghz')
        assert result['error']['code'] == 'wan_band_failed_unrestored', result
finally:
    helper.HOST, helper.DEVICE_SYS, helper.probe = real_host, real_sys, real_probe

# --- "(no IR)" channels: kept out of the AP-usable list, still counted for the
# WAN client's band report.
IW_NO_IR = '''
    Band 1:
        * 2412.0 MHz [1] (20.0 dBm)
    Band 2:
        * 5180.0 MHz [36] (17.0 dBm)
        * 5260.0 MHz [52] (23.0 dBm) (no IR)
        * 5745.0 MHz [149] (23.0 dBm)
    Band 4:
        * 5955.0 MHz [1] (12.0 dBm) (no IR)
'''
caps = helper.parse_radio_capabilities(IW_NO_IR)
assert caps['supported_channels']['5ghz'] == [36, 149], caps
assert caps['supported_channels']['6ghz'] == [], caps
assert caps['bands'] == ['2.4ghz', '5ghz', '6ghz'], 'WAN band reporting must still count no-IR frequencies'

# --- clone_mac: every mode shares one set/down/up/verify/restore path.
class MacHost:
    def __init__(self, previous='aa:bb:cc:dd:ee:ff', up_fail=0):
        self.setting = previous
        self.up_fail = up_fail
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:3] == ['/usr/bin/nmcli', 'connection', 'modify']:
            self.setting = argv[5]
            return Result(0)
        if argv[:3] == ['/usr/bin/nmcli', 'connection', 'up']:
            if self.up_fail:
                self.up_fail -= 1
                return Result(1)
            return Result(0)
        if argv[:2] == ['/usr/bin/nmcli', '-t']:
            return Result(0, 'HotelWiFi:wlan0')
        if argv[:2] == ['/usr/bin/nmcli', '-g'] and argv[2] == helper.MAC_SETTING:
            return Result(0, self.setting.replace(':', '\\:') + '\n')
        return Result(0)


def mac_act(host, **request):
    helper.HOST = host
    return helper.action('apply_mac_clone', {'action': 'apply_mac_clone', 'confirm': True, **request})


real_host, real_status, real_probe = helper.HOST, helper.status, helper.probe
helper.status = lambda: {'ok': True, 'status': {'marker': 'fresh'}}
try:
    helper.probe = lambda *a, **k: {'status': 'INTERNET_OK'}
    for request, expected in (({'mac': '02:11:22:33:44:55'}, '02:11:22:33:44:55'),
                              ({'mode': 'random'}, 'random'), ({'mode': 'default'}, '')):
        host = MacHost()
        result = mac_act(host, **request)
        assert result['ok'] is True and host.setting == expected, (request, result)
        assert result['status'] == {'marker': 'fresh'}, ('every mode must return status', request, result)
        order = [c[2] + ':' + (c[3] if c[2] == 'modify' else '') for c in host.calls if c[:2] == ['/usr/bin/nmcli', 'connection']]
        assert [c.split(':')[0] for c in order] == ['modify', 'down', 'up'], order

    # a captive portal counts as connected
    helper.probe = lambda *a, **k: {'status': 'CAPTIVE_PORTAL'}
    assert mac_act(MacHost(), mac='02:11:22:33:44:55')['ok'] is True

    # verification failure: previous identity restored via modify+down+up (all modes)
    helper.probe = lambda *a, **k: {'status': 'NO_ROUTE'}
    for request, code in (({'mac': '02:11:22:33:44:55'}, 'wan_reconnect_failed'),
                          ({'mode': 'random'}, 'mac_verify_failed'), ({'mode': 'default'}, 'mac_verify_failed')):
        host = MacHost()
        result = mac_act(host, **request)
        assert result['ok'] is False and result['error']['code'] == code, (request, result)
        assert host.setting == 'aa:bb:cc:dd:ee:ff', 'previous identity must be restored'
        verbs = [c[2] for c in host.calls if c[:2] == ['/usr/bin/nmcli', 'connection']]
        assert verbs == ['modify', 'down', 'up', 'modify', 'down', 'up'], ('restore must down before up', request, verbs)

    # restore cannot reconnect -> *_unrestored (every mode), never a silent success
    helper.probe = lambda *a, **k: {'status': 'INTERNET_OK'}
    for request, code in (({'mac': '02:11:22:33:44:55'}, 'wan_reconnect_failed_unrestored'),
                          ({'mode': 'random'}, 'mac_verify_failed_unrestored'),
                          ({'mode': 'default'}, 'mac_verify_failed_unrestored')):
        result = mac_act(MacHost(up_fail=2), **request)
        assert result['error']['code'] == code, (request, result)
    assert mac_act(MacHost(), mac='nonsense')['error']['code'] == 'invalid_mac'
finally:
    helper.HOST, helper.status, helper.probe = real_host, real_status, real_probe

print('wan band checks passed')
