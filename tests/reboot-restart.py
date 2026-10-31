#!/usr/bin/env python3
"""reboot and restart_services: a nonzero host command is a reported failure,
never ok; success paths run exactly the fixed command; invalid targets are
refused before the host is touched."""
import importlib.machinery
import importlib.util
import subprocess
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


class Host:
    def __init__(self, fail_on=None, returncode=1, timeout=False):
        self.calls = []
        self.fail_on = fail_on  # predicate on argv
        self.returncode = returncode
        self.timeout = timeout

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        if self.fail_on is None or self.fail_on(argv):
            if self.timeout:
                return subprocess.CompletedProcess(argv, 124, '', 'timed out after 30s')
            return subprocess.CompletedProcess(argv, self.returncode, '', 'refused')
        return subprocess.CompletedProcess(argv, 0, '', '')


def act(host, name, **fields):
    helper.HOST = host
    return helper.action(name, {'action': name, 'confirm': True, **fields})


real_host = helper.HOST
try:
    # --- reboot
    host = Host(fail_on=lambda argv: False)
    result = act(host, 'reboot')
    check(result.get('ok') is True and result.get('action') == 'reboot', 'reboot success: %s' % result)
    check(host.calls == [['/bin/systemctl', 'reboot']], 'reboot must run exactly systemctl reboot: %s' % host.calls)
    for rc in (1, 4, 124):
        host = Host(returncode=rc)
        result = act(host, 'reboot')
        check(result.get('ok') is False and result.get('error', {}).get('code') == 'reboot_failed',
              'reboot rc=%d must be reboot_failed: %s' % (rc, result))
        check('Reboot requested' not in str(result), 'a failed reboot must not say it was requested: %s' % result)
    host = Host(timeout=True)
    result = act(host, 'reboot')
    check(result.get('error', {}).get('code') == 'reboot_failed', 'a timed out reboot request must fail: %s' % result)
    helper.HOST = Host(fail_on=lambda argv: False)
    result = helper.action('reboot', {'action': 'reboot'})
    check(result.get('error', {}).get('code') == 'confirmation_required' and not helper.HOST.calls, 'reboot needs confirm and must not run without it')

    # --- restart_services
    for targets, units in ((['ap'], ['hostapd']), (['sqm'], [helper.SQM_SERVICE]),
                           (['ap', 'sqm'], ['hostapd', helper.SQM_SERVICE])):
        host = Host(fail_on=lambda argv: False)
        result = act(host, 'restart_services', targets=targets)
        check(result.get('ok') is True, 'restart %s must succeed: %s' % (targets, result))
        check(host.calls == [['/bin/systemctl', 'restart', u] for u in units], 'restart %s runs only its units in order: %s' % (targets, host.calls))

    host = Host(returncode=1)
    result = act(host, 'restart_services', targets=['ap', 'sqm'])
    check(result.get('ok') is False and result.get('error', {}).get('code') == 'restart_failed', 'a failed restart must be reported: %s' % result)
    check('AP restart failed' == result['error']['message'], 'the failure names the target that failed: %s' % result)
    check(host.calls == [['/bin/systemctl', 'restart', 'hostapd']], 'restart must stop at the first failure: %s' % host.calls)
    check('restarted' not in str(result), 'a failed restart must not say restarted: %s' % result)

    host = Host(fail_on=lambda argv: argv[2] == helper.SQM_SERVICE)
    result = act(host, 'restart_services', targets=['ap', 'sqm'])
    check(result.get('error', {}).get('message') == 'SQM restart failed' and len(host.calls) == 2,
          'the second target failing is still a failure naming SQM: %s' % result)
    host = Host(timeout=True)
    result = act(host, 'restart_services', targets=['sqm'])
    check(result.get('error', {}).get('code') == 'restart_failed', 'a timed out restart is a failure: %s' % result)

    # --- invalid targets never reach the host.
    for targets in (None, [], 'ap', ['wlan0'], ['ap', 'dnsmasq'], ['hostapd'], ['ap', 'ap;reboot'], [1], [['ap']], {'ap': 1}):
        host = Host(fail_on=lambda argv: False)
        result = act(host, 'restart_services', targets=targets) if targets is not None else act(host, 'restart_services')
        check(result.get('error', {}).get('code') == 'invalid_targets', 'targets %r must be refused: %s' % (targets, result))
        check(host.calls == [], 'refused targets %r must not touch the host: %s' % (targets, host.calls))
finally:
    helper.HOST = real_host

if failures:
    print('reboot/restart FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('reboot/restart checks passed')
