#!/usr/bin/env python3
import importlib.machinery
import importlib.util
from pathlib import Path

path = Path(__file__).parents[1] / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

internal = helper.parse_radio_capabilities('''
    Supported interface modes:
        * AP
    Band 1:
        * 2412.0 MHz [1]
        HT20/HT40
''')
assert internal['bands'] == ['2.4ghz']
assert internal['capabilities'] == ['ap', 'wifi4']
assert internal['supported_channels'] == {'2.4ghz': [1], '5ghz': [], '6ghz': []}

usb_6e = helper.parse_radio_capabilities('''
    Supported interface modes:
        * AP
    Band 1:
        * 2412.0 MHz [1] (20.0 dBm)
        * 2437.0 MHz [6] (20.0 dBm)
        * 2484.0 MHz [14] (20.0 dBm) (disabled)
        HT20/HT40
    Band 2:
        * 5180.0 MHz [36] (17.0 dBm)
        * 5520.0 MHz [104] (24.0 dBm) (no IR, radar detection)
        VHT80
    Band 4:
        * 5955.0 MHz [1] (23.0 dBm)
        * 6135.0 MHz [37] (23.0 dBm)
        HE80/5GHz
''')
assert usb_6e['bands'] == ['2.4ghz', '5ghz', '6ghz']
assert usb_6e['capabilities'] == ['ap', 'wifi4', 'wifi5', 'wifi6', 'wifi6e']
# Radar (DFS) channels are excluded from the allowed channel set.
assert usb_6e['supported_channels'] == {'2.4ghz': [1, 6], '5ghz': [36], '6ghz': [1, 37]}

assert helper.parse_radio_capabilities('') == {'bands': [], 'capabilities': [],
                                               'supported_channels': {'2.4ghz': [], '5ghz': [], '6ghz': []}}
print('radio capability checks passed')
