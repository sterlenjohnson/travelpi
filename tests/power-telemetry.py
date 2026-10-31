#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import os
import shutil
import tempfile
import time
from pathlib import Path

path = Path(__file__).parents[1] / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

clean = helper.decode_throttle_bits(0x0)
assert clean['signal'] == 'clean'
assert all(clean[field] is False for field in helper.THROTTLE_FLAG_FIELDS)

undervolt_now = helper.decode_throttle_bits(0x1)
assert undervolt_now['signal'] == 'undervolt-now'
assert undervolt_now['under_volt_now'] is True
assert undervolt_now['under_volt_history'] is False

undervolt_history = helper.decode_throttle_bits(0x10)
assert undervolt_history['signal'] == 'undervolt-history'
assert undervolt_history['under_volt_history'] is True
assert undervolt_history['under_volt_now'] is False
assert helper.decode_throttle_bits(0x10000)['signal'] == 'undervolt-history'
assert helper.decode_throttle_bits(0x10000)['under_volt_history'] is True

temperature_now = helper.decode_throttle_bits(0x8)
assert temperature_now['signal'] == 'temperature-now'
assert temperature_now['temp_throttle_now'] is True

throttle_now = helper.decode_throttle_bits(0x4)
assert throttle_now['signal'] == 'throttle-now'
assert throttle_now['throttle_now'] is True
assert throttle_now['throttle_history'] is False
assert helper.decode_throttle_bits(0x2)['signal'] == 'throttle-now'

throttle_history = helper.decode_throttle_bits(0x40)
assert throttle_history['signal'] == 'throttle-history'
assert throttle_history['throttle_history'] is True
assert throttle_history['throttle_now'] is False
assert helper.decode_throttle_bits(0x20)['signal'] == 'throttle-history'
assert helper.decode_throttle_bits(0x20000)['signal'] == 'throttle-history'
assert helper.decode_throttle_bits(0x40000)['signal'] == 'throttle-history'
assert helper.decode_throttle_bits(0x80)['signal'] == 'temperature-history'
assert helper.decode_throttle_bits(0x80000)['signal'] == 'temperature-history'

combined = helper.decode_throttle_bits(0x11)
assert combined['signal'] == 'undervolt-now'
assert combined['under_volt_history'] is True
assert combined['under_volt_now'] is True
assert helper.decode_throttle_bits(0x10001)['signal'] == 'undervolt-now'
assert helper.decode_throttle_bits(0x30)['signal'] == 'undervolt-history'
assert helper.decode_throttle_bits(0x60)['signal'] == 'throttle-history'
assert helper.decode_throttle_bits(0x11)['signal'] == helper.decode_throttle_bits(0x1)['signal']
assert set(helper.decode_throttle_bits(0x31)) == set(helper.THROTTLE_FLAG_FIELDS) | {'signal'}

assert helper.THROTTLE_DETAILS['clean'] == 'No current or historical power-throttle flags.'
assert helper.THROTTLE_DETAILS['undervolt-now'] == 'Under-voltage is happening now — reduce load / check both power sources.'
assert helper.THROTTLE_DETAILS['undervolt-history'] == 'Under-voltage occurred since this boot (check the Pi Zero 2 W dual power sources).'
assert helper.THROTTLE_DETAILS['throttle-now'] == 'CPU throttling is active.'
assert helper.THROTTLE_DETAILS['throttle-history'] == 'CPU throttling is active.'
assert helper.THROTTLE_DETAILS['temperature-now'] == 'Temperature throttling flags are present.'
assert helper.THROTTLE_DETAILS['temperature-history'] == 'Temperature throttling flags are present.'
assert helper.decode_throttle_bits(0x20)['signal'] in helper.THROTTLE_DETAILS

assert helper.parse_core_volts('volt=1.2563V') == 1.2563
assert helper.parse_core_volts('volt=1.2V') == 1.2
assert helper.parse_core_volts('volt=1V') == 1.0
assert helper.parse_core_volts('') is None
assert helper.parse_core_volts('volt=unsupported') is None

assert helper.USB_DEVICE_RE.match('1-1')
assert helper.USB_DEVICE_RE.match('1-1.2')
assert helper.USB_DEVICE_RE.match('1-1.10.3')
assert helper.USB_DEVICE_RE.match('10-1')
assert helper.USB_DEVICE_RE.match('1-1:1.0') is None
assert helper.USB_DEVICE_RE.match('usb1') is None
assert helper.USB_DEVICE_RE.match('pci0000:00') is None

sandbox = Path(tempfile.mkdtemp(prefix='travelpi-power-'))
real_hwmon = helper.HWMON_SYS
real_usb = helper.USB_BUS_SYS
try:
    helper.HWMON_SYS = sandbox
    helper.USB_BUS_SYS = sandbox
    sensor = sandbox / 'hwmon7'
    sensor.mkdir()
    (sensor / 'name').write_text('INA219 7\n')
    (sensor / 'in2_input').write_text('412300\n')
    (sensor / 'power1_input').write_text('2100\n')
    reading = helper.current_sensor_reading()
    assert reading == {'current_sensor': 'ina219', 'current_ma': 412.3, 'power_w': 2.1}

    other = sandbox / 'hwmon8'
    other.mkdir()
    (other / 'name').write_text('cpu_thermal\n')
    partial = sandbox / 'hwmon9'
    shutil.rmtree(sensor)
    partial.mkdir()
    (partial / 'name').write_text('ina226\n')
    reading = helper.current_sensor_reading()
    assert reading == {'current_sensor': 'ina226', 'current_ma': None, 'power_w': None}

    shutil.rmtree(partial)
    assert helper.current_sensor_reading() == {'current_sensor': None, 'current_ma': None, 'power_w': None}

    for name in ('usb1', 'usb2', '1-1', '1-1.2', '1-1:1.0', 'pci0000:00:00.0'):
        (sandbox / name).mkdir()
    otg = helper.usb_otg_status()
    assert otg == {'usb_otg_present': True, 'usb_devices': 2, 'usb_demand_ma': 0}
    shutil.rmtree(sandbox / 'usb1')
    assert helper.usb_otg_status() == {'usb_otg_present': False, 'usb_devices': 2, 'usb_demand_ma': 0}

    real_log = helper.POWER_LOG
    helper.POWER_LOG = sandbox / 'power-log.jsonl'
    assert helper.power_recorder_status() == {'unexpected_shutdown': None, 'power_loss_count': None}
    (sandbox / 'power-log.jsonl').write_text('not json\n')
    assert helper.power_recorder_status() == {'unexpected_shutdown': None, 'power_loss_count': None}
    (sandbox / 'power-log.jsonl').write_text(
        '{"event":"boot"}\n{"event":"clean-shutdown"}\n{"event":"boot"}\n')
    assert helper.power_recorder_status() == {'unexpected_shutdown': False, 'power_loss_count': 0}
    (sandbox / 'power-log.jsonl').write_text(
        '{"event":"boot"}\n{"event":"unexpected-shutdown"}\n{"event":"boot"}\n'
        '{"event":"unexpected-shutdown"}\n')
    assert helper.power_recorder_status() == {'unexpected_shutdown': True, 'power_loss_count': 2}
    (sandbox / 'power-log.jsonl').write_text(
        '{"event":"boot"}\n{"event":"unexpected-shutdown"}\n{"event":"boot"}\n'
        '{"event":"clean-shutdown"}\n{"event":"boot"}\n')
    assert helper.power_recorder_status() == {'unexpected_shutdown': False, 'power_loss_count': 1}
    helper.POWER_LOG = real_log

    for name in ('1-1.2', '1-1.4'):
        (sandbox / name).mkdir(exist_ok=True)
        (sandbox / name / 'bMaxPower').write_text('100mA\n')
    assert helper.usb_otg_status()['usb_demand_ma'] == 200

    real_config = helper.FIRMWARE_CONFIG
    helper.FIRMWARE_CONFIG = sandbox / 'config.txt'
    assert helper.firmware_config_overrides() is None
    (sandbox / 'config.txt').write_text(
        '#over_voltage=6\narm_freq=1000\nsdram_freq=600\ndtoverlay=wc-otp\ncore_freq=500 # arm_freq=9999\n')
    overrides = helper.firmware_config_overrides()
    assert overrides == ['arm_freq=1000', 'sdram_freq=600', 'core_freq=500'], overrides
    helper.FIRMWARE_CONFIG = real_config

    real_cmd = helper.CLOCK_SYNC_CMD
    helper.CLOCK_SYNC_CMD = ['/bin/echo', 'yes']
    assert helper.clock_synced() is True
    helper.CLOCK_SYNC_CMD = ['/bin/echo', 'no']
    assert helper.clock_synced() is False
    helper.CLOCK_SYNC_CMD = ['/bin/definitely-missing']
    assert helper.clock_synced() is None
    helper.CLOCK_SYNC_CMD = real_cmd

    real_journal = helper.KERNEL_JOURNAL_CMD
    real_cache = helper.JOURNAL_EVENTS_CACHE
    helper.JOURNAL_EVENTS_CACHE = str(sandbox / 'journal.json')
    helper.KERNEL_JOURNAL_CMD = ['/usr/bin/printf',
                                  'Throttling detected at 1s\n'
                                  'mt7921u 1-1: device reset\n'
                                  'mt7925u 1-1.2:1.0: device reset\n'
                                  'EXT4-fs error (device mmcblk2)\n'
                                  'mt7921u 1-1.2:1.0: vendor request req:63 off:d058 failed:-110\n']
    events = helper.journal_power_events()
    assert events == {'throttle_events': 1, 'radio_reset_events': 2, 'radio_link_events': 1, 'fs_errors': 1}, events
    events = helper.journal_power_events()  # served from cache, command would now fail
    helper.KERNEL_JOURNAL_CMD = ['/bin/definitely-missing']
    assert helper.journal_power_events() == {'throttle_events': 1, 'radio_reset_events': 2, 'radio_link_events': 1, 'fs_errors': 1}
    os.remove(helper.JOURNAL_EVENTS_CACHE)
    assert helper.journal_power_events() == {'throttle_events': 0, 'radio_reset_events': 0, 'radio_link_events': 0, 'fs_errors': 0}
    helper.KERNEL_JOURNAL_CMD = real_journal
    helper.JOURNAL_EVENTS_CACHE = real_cache

    power = helper.power_status()
finally:
    helper.HWMON_SYS = real_hwmon
    helper.USB_BUS_SYS = real_usb
    helper.POWER_LOG = real_log
    helper.FIRMWARE_CONFIG = real_config
    helper.CLOCK_SYNC_CMD = real_cmd
    helper.KERNEL_JOURNAL_CMD = real_journal
    helper.JOURNAL_EVENTS_CACHE = real_cache
    shutil.rmtree(sandbox, ignore_errors=True)

for key in ('state', 'temperature_c', 'throttled', 'detail', 'signal', 'raw_throttled',
            'core_volts', 'current_ma', 'power_w', 'current_sensor', 'usb_otg_present',
            'usb_devices', 'usb_demand_ma', 'unexpected_shutdown', 'power_loss_count',
            'clock_synced', 'storage_risk'):
    assert key in power
for key in helper.THROTTLE_FLAG_FIELDS:
    assert key in power

assert power['state'] in ('ok', 'warning', 'unknown')
assert power['signal'] in helper.POWER_SIGNALS
assert power['raw_throttled'] == power['throttled']
assert isinstance(power['usb_otg_present'], bool)
assert power['usb_devices'] is None or isinstance(power['usb_devices'], int)
assert power['current_sensor'] is None or power['current_sensor'] in helper.INA_SENSORS
for key in ('core_volts', 'current_ma', 'power_w'):
    assert power[key] is None or isinstance(power[key], float)

if power['throttled'] is None:
    assert power['signal'] == 'unavailable'
    assert all(power[key] is None for key in helper.THROTTLE_FLAG_FIELDS)
    assert power['detail'] in ('Power telemetry unavailable.', 'Temperature is available; power flags are unavailable.')
else:
    assert power['signal'] != 'unavailable'
    assert all(isinstance(power[key], bool) for key in helper.THROTTLE_FLAG_FIELDS)
    assert power['state'] == ('ok' if power['signal'] == 'clean' else 'warning')
    assert power['detail'] == helper.THROTTLE_DETAILS[power['signal']]

ap_ev = helper.ap_evidence()
assert set(ap_ev) == {'carrier', 'stations'}
assert ap_ev['carrier'] in (None, True, False)
assert ap_ev['stations'] is None or isinstance(ap_ev['stations'], int)

# radio auto-recovery watchdog visibility: event log + heartbeat liveness
watch_dir = tempfile.mkdtemp(prefix='travelpi-watch-')
helper.RADIO_RECOVERY_LOG = os.path.join(watch_dir, 'radio-recoveries.jsonl')
helper.RADIO_WATCH_HEARTBEAT = os.path.join(watch_dir, 'radio-watch-heartbeat')
watch = helper.radio_watchdog_status()
assert watch == {'radio_recovery_events': 0, 'last_radio_recovery': None,
                 'radio_watchdog': 'absent'}, watch
Path(helper.RADIO_RECOVERY_LOG).write_text(
    '{"ts": 111, "outcome": "link-cycle"}\n{"ts": 222, "outcome": "usb-rebind"}\n')
Path(helper.RADIO_WATCH_HEARTBEAT).write_text('')
watch = helper.radio_watchdog_status()
assert watch['radio_recovery_events'] == 2, watch
assert watch['last_radio_recovery'] == 222, watch
assert watch['radio_watchdog'] == 'armed', watch
past = time.time() - 600
os.utime(helper.RADIO_WATCH_HEARTBEAT, (past, past))
assert helper.radio_watchdog_status()['radio_watchdog'] == 'stale'
shutil.rmtree(watch_dir)

# memory/swap guard visibility: action log + heartbeat liveness
guard_dir = tempfile.mkdtemp(prefix='travelpi-guard-')
helper.MEMGUARD_LOG = os.path.join(guard_dir, 'mem-guard.jsonl')
helper.MEM_WATCH_HEARTBEAT = os.path.join(guard_dir, 'mem-watch-heartbeat')
guard = helper.memguard_status()
assert guard == {'mem_guard_events': 0, 'last_mem_guard_event': None,
                 'last_mem_guard_action': None, 'mem_watchdog': 'absent'}, guard
Path(helper.MEMGUARD_LOG).write_text(
    '{"ts": "2026-10-28T11:00:00Z", "action": "stop-exim4", "mem_avail_mb": 24,'
    ' "swap_free_mb": 20, "detail": "x"}\n'
    '{"ts": "2026-10-28T11:05:00Z", "action": "kill", "mem_avail_mb": 18,'
    ' "swap_free_mb": 12, "detail": "SIGKILL pid 999 (evil 90MB)"}\n')
Path(helper.MEM_WATCH_HEARTBEAT).write_text('')
guard = helper.memguard_status()
assert guard['mem_guard_events'] == 2, guard
assert guard['last_mem_guard_event'] == '2026-10-28T11:05:00Z', guard
assert guard['last_mem_guard_action'] == 'kill', guard
assert guard['mem_watchdog'] == 'armed', guard
# A heartbeat touched "in the future" (clock stepped back after NTP sync on an
# RTC-less host) is fresh, never a wrong stale/absent flip.
future = time.time() + 3600
os.utime(helper.MEM_WATCH_HEARTBEAT, (future, future))
assert helper.memguard_status()['mem_watchdog'] == 'armed'
os.utime(helper.MEM_WATCH_HEARTBEAT, (time.time(), time.time()))
past = time.time() - 600
os.utime(helper.MEM_WATCH_HEARTBEAT, (past, past))
assert helper.memguard_status()['mem_watchdog'] == 'stale'
shutil.rmtree(guard_dir)

# captive-portal hint: stubbed neverssl probe (redirect to private = portal)
portal_cache = os.path.join(tempfile.mkdtemp(prefix='travelpi-portal-'), 'portal-cache.json')
orig_portal = helper.PORTAL_PROBE_CMD
orig_portal_cache = helper.PORTAL_CACHE
helper.PORTAL_CACHE = portal_cache
helper.PORTAL_PROBE_CMD = ['/usr/bin/printf', '302 http://172.20.0.1/portal/login\n']
orig_route_status = helper.route_status
helper.route_status = lambda: {}
assert helper.portal_status()['state'] == 'unknown', 'no WAN default route must not claim a portal'
assert not os.path.exists(portal_cache), 'offline unknown must not be cached'
helper.route_status = lambda: {'gateway': '172.20.0.1', 'interface': 'wlan0'}
portal = helper.portal_status()
assert portal['state'] == 'portal' and portal['portal_url'] == 'http://172.20.0.1/portal/login', portal
cached = helper.portal_status()
assert cached['state'] == 'portal' and cached['age_s'] >= 0, cached
os.remove(portal_cache)
helper.PORTAL_PROBE_CMD = ['/usr/bin/printf', '200 \n']
assert helper.portal_status()['state'] == 'online'
os.remove(portal_cache)
helper.PORTAL_PROBE_CMD = ['/usr/bin/printf', ' \n']
class _NoNet:
    returncode = 7
    stdout = ''
helper_run_real = helper.run
helper.run = lambda *a, **k: _NoNet()
assert helper.portal_status()['state'] == 'blocked'
helper.run = helper_run_real
helper.route_status = orig_route_status
helper.PORTAL_CACHE = orig_portal_cache
helper.PORTAL_PROBE_CMD = orig_portal

# DNS responder probe (the unprivileged-Cockpit truth path): stubbed dig
orig_probe = helper.ADGUARD_DNS_PROBE_CMD
helper.ADGUARD_DNS_PROBE_CMD = ['/usr/bin/printf', '93.184.216.34\n']
assert helper.dns_responder_live() is True
helper.ADGUARD_DNS_PROBE_CMD = ['/usr/bin/printf', '']
assert helper.dns_responder_live() is False
helper.ADGUARD_DNS_PROBE_CMD = ['/bin/definitely-missing']
assert helper.dns_responder_live() is False
helper.ADGUARD_DNS_PROBE_CMD = orig_probe

print('power telemetry checks passed')

# ap.wifi6 comes from hostapd.conf ieee80211ax, not from the frequency.
ap_dir = tempfile.mkdtemp(prefix='travelpi-wifi6-')
real_hostapd = helper.HOSTAPD
helper.HOSTAPD = Path(ap_dir) / 'hostapd.conf'
helper.HOSTAPD.write_text('interface=wlan1\nhw_mode=a\nchannel=36\nieee80211ax=1\n')
assert helper.ap_wifi6() is True
helper.HOSTAPD.write_text('interface=wlan1\nhw_mode=a\nchannel=36\nieee80211ax=0\n')
assert helper.ap_wifi6() is False, '5 GHz alone must not claim Wi-Fi 6'
helper.HOSTAPD.write_text('interface=wlan1\nhw_mode=a\nchannel=36\n')
assert helper.ap_wifi6() is False
# Unreadable config (unprivileged status): fall back to the radio's HE capability.
helper.HOSTAPD = Path(ap_dir) / 'missing.conf'
real_caps = helper.radio_phy_capabilities
helper.radio_phy_capabilities = lambda interface: {'capabilities': ['ap', 'wifi6']}
assert helper.ap_wifi6() is True
helper.radio_phy_capabilities = lambda interface: {'capabilities': ['ap', 'wifi4']}
assert helper.ap_wifi6() is False
helper.radio_phy_capabilities = real_caps
helper.HOSTAPD = real_hostapd
shutil.rmtree(ap_dir)
print('power telemetry extra checks passed')
