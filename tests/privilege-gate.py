#!/usr/bin/env python3
"""CLI privilege gates (scan, pd, action) through the helper's EUID seam, so
the refusal is tested whether the suite runs as root or not.

Unprivileged: each root-only command answers not_privileged, exits 1 and never
reaches the host (HOST raises if touched, and the scan/probe/action bodies are
tripwires). Privileged: the gate opens and the command reaches its body; a
malformed action body is refused before any host call.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
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


class TripwireHost:
    def __init__(self):
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append(list(argv))
        raise AssertionError('the host must not be reached: %s' % argv)


def cli(*args, stdin=''):
    out = io.StringIO()
    old_argv, old_stdin = sys.argv, sys.stdin
    sys.argv = ['travelpi-cockpit', *args]
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out):
            code = helper.main()
    finally:
        sys.argv, sys.stdin = old_argv, old_stdin
    return code, json.loads(out.getvalue())


saved = (helper.HOST, helper.EUID, helper.wifi_scan, helper.dhcpv6_pd_probe, helper.action)
reached = []
helper.wifi_scan = lambda: reached.append('scan') or {'ok': True, 'networks': []}
helper.dhcpv6_pd_probe = lambda iface=None: reached.append('pd') or {'ok': True, 'action': 'pd_probe', 'pd': {'state': 'not_offered'}}
helper.action = lambda name, request: reached.append('action:%s' % name) or {'ok': True, 'action': name}
helper.HOST = TripwireHost()
try:
    # --- unprivileged: every root-only command refuses and reaches nothing.
    helper.EUID = lambda: 1000
    request = json.dumps({'action': 'vpn_toggle', 'provider': 'tailscale', 'enabled': False, 'confirm': True})
    for args, stdin in ((('scan',), ''), (('pd',), ''), (('action',), request)):
        reached.clear()
        code, payload = cli(*args, stdin=stdin)
        check(code == 1 and payload.get('ok') is False and payload.get('error', {}).get('code') == 'not_privileged',
              '%s must refuse an unprivileged caller: %s %s' % (args[0], code, payload))
        check(reached == [] and helper.HOST.calls == [], '%s refusal must not reach its body or the host: %s' % (args[0], reached))

    # --- unknown commands stay refused as invalid, whoever asks.
    code, payload = cli('bogus')
    check(payload.get('error', {}).get('code') == 'invalid_command', 'unknown commands stay invalid_command')

    # --- privileged: the gate opens.
    helper.EUID = lambda: 0
    reached.clear()
    code, payload = cli('scan')
    check(code == 0 and payload.get('ok') is True and reached == ['scan'], 'root scan must reach wifi_scan: %s %s' % (payload, reached))
    reached.clear()
    code, payload = cli('pd')
    check(code == 0 and reached == ['pd'], 'root pd must reach the probe: %s %s' % (payload, reached))
    reached.clear()
    code, payload = cli('action', stdin=request)
    check(code == 0 and reached == ['action:vpn_toggle'], 'root action must reach the action dispatcher: %s %s' % (payload, reached))
    reached.clear()
    code, payload = cli('action', stdin='[1, 2]')
    check(code == 1 and payload.get('error', {}).get('code') == 'invalid_request' and reached == [],
          'a non-object action body must be refused before dispatch: %s %s' % (payload, reached))
    code, payload = cli('action', stdin='not json')
    check(payload.get('error', {}).get('code') == 'invalid_request' and reached == [], 'garbage action body must be refused: %s' % payload)
finally:
    helper.HOST, helper.EUID, helper.wifi_scan, helper.dhcpv6_pd_probe, helper.action = saved

if failures:
    print('privilege gate FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('privilege gate checks passed')
