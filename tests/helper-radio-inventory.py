#!/usr/bin/env python3
import importlib.machinery
import importlib.util
from pathlib import Path

path = Path(__file__).parents[1] / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

class FakePath:
    def __init__(self, exists, resolved=''):
        self._exists = exists
        self._resolved = resolved
    def exists(self):
        return self._exists
    def joinpath(self, _):
        return self
    def resolve(self):
        return Path(self._resolved)
    def __truediv__(self, _):
        return self

class FakeRoot:
    def __init__(self, devices):
        self.devices = devices
    def __truediv__(self, interface):
        return self.devices.get(interface, FakePath(False))

helper.DEVICE_SYS = FakeRoot({
    'wlan0': FakePath(True, '/sys/devices/platform/mmc1/wlan0'),
    'wlan1': FakePath(True, '/sys/devices/usb1/wlan1'),
    'wlan2': FakePath(True, '/sys/devices/platform/other/wlan2'),
})

internal = helper.interface_hardware('wlan0')
assert internal['role'] == 'wan'
assert internal['transport'] == 'SDIO'
assert internal['label'] == 'Pi internal Wi-Fi'
assert internal['capabilities'] == []

usb = helper.interface_hardware('wlan1')
assert usb['role'] == 'ap'
assert usb['transport'] == 'USB'
assert usb['label'] == 'USB Wi-Fi adapter'
assert usb['capabilities'] == []

absent = helper.interface_hardware('wlan9')
assert absent['present'] is False
assert absent['role'] == 'unknown'
assert absent['capabilities'] == []

unknown = helper.interface_hardware('wlan2')
assert unknown['present'] is True
assert unknown['model'] == 'Unknown hardware'
assert unknown['transport'] == 'Unknown'
assert set(unknown) == {'interface', 'role', 'present', 'label', 'model', 'transport', 'driver', 'bands', 'capabilities'}

print('radio inventory checks passed')
