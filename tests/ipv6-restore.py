#!/usr/bin/env python3
"""set_ipv6 through the HOST seam with the networkd files in a sandbox: the
ra-off drop-in is reverted to its previous state (present with its exact
content, or absent) when networkd cannot reload or reconfigure, the failure
is reported, and the on/off success paths write and remove the drop-in."""
import importlib.machinery
import importlib.util
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
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.stdout = ''
        self.stderr = ''


class NetworkdHost:
    def __init__(self, dropin, reload_rc=0, reconfigure_rc=0):
        self.dropin = dropin
        self.rcs = {'reload': reload_rc, 'reconfigure': reconfigure_rc}
        self.calls = []
        self.dropin_at_call = []  # drop-in content seen by each networkctl call

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.dropin_at_call.append(self.dropin.read_text() if self.dropin.exists() else None)
        if argv[:1] == ['/usr/bin/networkctl']:
            # Only the first attempt fails; the restore's own reload must work.
            attempt = [c for c in self.calls if c[:2] == argv[:2]]
            return Result(self.rcs[argv[1]] if len(attempt) == 1 else 0)
        return Result(0)

    def verbs(self):
        return [c[1:] for c in self.calls if c[:1] == ['/usr/bin/networkctl']]


sandbox = Path(_mkdtemp(prefix='travelpi-ipv6-'))
network = sandbox / '070-travelpi-ap.network'
dropin = sandbox / '070-travelpi-ap.network.d' / 'ra-off.conf'
ula = sandbox / 'ula-prefix'
OFF = '[Network]\nIPv6SendRA=no\n'
CUSTOM = '[Network]\nIPv6SendRA=no\n# operator note\n'

saved = (helper.HOST, helper.AP_NETWORK_FILE, helper.AP_RA_OFF_DROPIN, helper.ULA_PREFIX_FILE)
helper.AP_NETWORK_FILE = str(network)
helper.AP_RA_OFF_DROPIN = str(dropin)
helper.ULA_PREFIX_FILE = str(ula)


def reset(previous=None, with_network=True, with_ula=True):
    for item in sandbox.rglob('*'):
        if item.is_file():
            item.unlink()
    network.write_text('[Match]\nName=wlan1\n')
    if not with_network:
        network.unlink()
    if with_ula:
        ula.write_text('fd12:3456:789a:1::/64\n')
    if previous is not None:
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(previous)


def act(host, mode):
    helper.HOST = host
    return helper.action('set_ipv6', {'action': 'set_ipv6', 'confirm': True, 'mode': mode})


def state():
    return dropin.read_text() if dropin.exists() else None


try:
    # --- success paths.
    reset()
    host = NetworkdHost(dropin)
    result = act(host, 'off')
    check(result.get('ok') is True and state() == OFF, 'off must write the ra-off drop-in: %s %r' % (result, state()))
    check(host.verbs() == [['reload'], ['reconfigure', 'wlan1']], 'networkd must be reloaded then reconfigured, never restarted: %s' % host.verbs())
    check(host.dropin_at_call[0] == OFF, 'the drop-in must be in place before networkd reloads')
    check(not any('restart' in c for c in host.calls), 'set_ipv6 must not restart networkd (it would flush the AP addresses)')

    reset(previous=OFF)
    host = NetworkdHost(dropin)
    result = act(host, 'on')
    check(result.get('ok') is True and state() is None, 'on must remove the ra-off drop-in: %s %r' % (result, state()))
    check('ULA' in result.get('message', ''), 'on message: %s' % result)
    reset()
    result = act(NetworkdHost(dropin), 'on')
    check(result.get('ok') is True and state() is None, 'on with no drop-in is idempotent: %s' % result)

    # --- refusals change nothing and run nothing.
    for label, kwargs, mode, code in (('bad mode', {}, 'maybe', 'invalid_mode'),
                                      ('no profile', {'with_network': False}, 'off', 'unavailable'),
                                      ('on without a ULA prefix', {'with_ula': False}, 'on', 'unavailable')):
        reset(previous=CUSTOM, **kwargs)
        host = NetworkdHost(dropin)
        result = act(host, mode)
        check(result.get('error', {}).get('code') == code, '%s must refuse with %s: %s' % (label, code, result))
        check(host.calls == [] and state() == CUSTOM, '%s must not run networkctl or change the drop-in' % label)

    # --- failures revert the drop-in and are reported.
    for failing, previous, mode in (('reload', None, 'off'), ('reconfigure', None, 'off'),
                                    ('reload', OFF, 'on'), ('reconfigure', CUSTOM, 'on'),
                                    ('reconfigure', CUSTOM, 'off'), ('reload', None, 'on')):
        reset(previous=previous)
        host = NetworkdHost(dropin, reload_rc=1 if failing == 'reload' else 0,
                            reconfigure_rc=1 if failing == 'reconfigure' else 0)
        result = act(host, mode)
        label = '%s fails, previous=%r, mode=%s' % (failing, previous, mode)
        check(result.get('ok') is False and result.get('error', {}).get('code') == 'ra_change_failed', label + ': failure must be reported: %s' % result)
        check('previous setting was restored' in result['error']['message'], label + ': must say it restored')
        check(state() == previous, label + ': the drop-in must be back to %r, is %r' % (previous, state()))
        verbs = host.verbs()
        check(verbs[-2:] == [['reload'], ['reconfigure', 'wlan1']], label + ': networkd must be told about the restore too: %s' % verbs)
        check('Router advertisements' not in str(result), label + ': a failure must not claim a change')

    # --- the drop-in cannot be written: nothing changed, no networkd call.
    reset(previous=OFF)
    dropin.parent.chmod(0o500)
    probe = dropin.parent / 'probe'
    try:
        probe.write_text('x')
        writable = True
        probe.unlink()
    except OSError:
        writable = False
    if not writable:  # not root: the write must fail cleanly
        host = NetworkdHost(dropin)
        dropin.chmod(0o400)
        result = act(host, 'off')
        check(result.get('error', {}).get('code') == 'ra_change_failed' and host.calls == [], 'an unwritable drop-in must fail before networkd: %s' % result)
    dropin.parent.chmod(0o700)
    dropin.chmod(0o600)
finally:
    for _path, _mode in ((dropin.parent, 0o700), (dropin, 0o600)):
        try:
            _path.chmod(_mode)
        except OSError:
            pass
    helper.HOST, helper.AP_NETWORK_FILE, helper.AP_RA_OFF_DROPIN, helper.ULA_PREFIX_FILE = saved

if failures:
    print('ipv6 restore FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('ipv6 restore checks passed')
