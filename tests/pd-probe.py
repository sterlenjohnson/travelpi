#!/usr/bin/env python3
"""DHCPv6 prefix-delegation probe: pure packet build/parse, the seam-stubbed
probe states and CLI dispatch. No sockets are opened."""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
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


MAC = bytes.fromhex('02aabbccdd01')
XID = b'\x01\x02\x03'
PREFIX = bytes.fromhex('20010db8000000000000000000000000')


def opt(code, body):
    return code.to_bytes(2, 'big') + len(body).to_bytes(2, 'big') + body


def iaprefix(plen=60, valid=3600, prefix=PREFIX):
    return opt(26, (1800).to_bytes(4, 'big') + valid.to_bytes(4, 'big') + bytes([plen]) + prefix)


def ia_pd(*subs):
    return opt(25, (1).to_bytes(4, 'big') + bytes(8) + b''.join(subs))


def reply(*opts, msg=2, xid=XID):
    return bytes([msg]) + xid + b''.join(opts) + b''

# build
pkt = helper.build_pd_solicit(MAC, XID)
check(pkt[0] == 1 and pkt[1:4] == XID, 'solicit header')
check(opt(1, b'\x00\x03\x00\x01' + MAC) in pkt, 'DUID-LL client id with MAC')
check(opt(8, b'\x00\x00') in pkt, 'elapsed time option')
check(opt(25, (1).to_bytes(4, 'big') + bytes(8)) in pkt, 'IA_PD iaid 1 t1=t2=0')
check(pkt[0] != 3, 'never a REQUEST')
try:
    helper.build_pd_solicit(b'\x00', XID)
    check(False, 'bad mac must raise')
except ValueError:
    pass

# parse: offered /60
got = helper.parse_pd_reply(reply(opt(2, b'srv'), ia_pd(iaprefix())), XID)
check(got and got['prefix'] == '2001:db8::' and got['prefix_len'] == 60 and got['valid_s'] == 3600, f'offered parse {got}')
# parse: NoPrefixAvail nested and top-level
got = helper.parse_pd_reply(reply(ia_pd(opt(13, b'\x00\x06nope'))), XID)
check(got and got['status'] == 6 and got['prefix'] is None, f'nested status {got}')
got = helper.parse_pd_reply(reply(opt(13, b'\x00\x06'), msg=7), XID)
check(got and got['status'] == 6, f'top-level status {got}')
# malformed / wrong xid / wrong type / short
check(helper.parse_pd_reply(b'', XID) is None, 'empty')
check(helper.parse_pd_reply(b'\x02\x01', XID) is None, 'short header')
check(helper.parse_pd_reply(reply(ia_pd(iaprefix()), xid=b'\x09\x09\x09'), XID) is None, 'wrong xid')
check(helper.parse_pd_reply(reply(ia_pd(iaprefix()), msg=1), XID) is None, 'solicit is not an answer')
check(helper.parse_pd_reply(reply(ia_pd(iaprefix()))[:-5], XID) is None, 'truncated option body')
check(helper.parse_pd_reply(reply(opt(25, b'\x00\x01')), XID) is None, 'short IA_PD')
check(helper.parse_pd_reply(reply(ia_pd(opt(26, b'\x00' * 10))), XID) is None, 'short IAPREFIX')
check(helper.parse_pd_reply(reply(ia_pd(iaprefix(plen=200))), XID) is None, 'bad prefix length')
check(helper.parse_pd_reply(reply(b'\x00\x01\x00'), XID) is None, 'truncated option header')

# datagram filter
def udp(sport, dport, payload):
    return sport.to_bytes(2, 'big') + dport.to_bytes(2, 'big') + (8 + len(payload)).to_bytes(2, 'big') + b'\0\0' + payload
check(helper.match_dhcpv6_datagram(udp(547, 546, b'abcd')) == b'abcd', 'datagram match')
check(helper.match_dhcpv6_datagram(udp(53, 546, b'abcd')) is None, 'wrong sport')
check(helper.match_dhcpv6_datagram(udp(547, 1000, b'abcd')) is None, 'wrong dport')
check(helper.match_dhcpv6_datagram(b'\x02\x23') is None, 'short datagram')

# probe with seams and a sandboxed sysfs
tmp = Path(tempfile.mkdtemp())
(tmp / 'sys' / 'wlan0').mkdir(parents=True)
(tmp / 'sys' / 'wlan0' / 'address').write_text('02:aa:bb:cc:dd:01\n')
(tmp / 'sys' / 'wlan0' / 'operstate').write_text('up\n')
inet6 = tmp / 'if_inet6'
inet6.write_text('fe80000000000000000000000000dd01 03 40 20 80 wlan0\n')
helper.DEVICE_SYS = tmp / 'sys'
helper.PD_IF_INET6 = inet6
helper.PD_EUID = lambda: 0
calls = []


def stub(answer):
    def transport(interface, packet, xid, timeout):
        calls.append((interface, packet, timeout))
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(xid)
        return answer
    helper.PD_TRANSPORT = transport


stub(lambda xid: (reply(ia_pd(iaprefix()), xid=xid), 'fe80::1'))
r = helper.dhcpv6_pd_probe()
pd = r['pd']
check(r['ok'] and r['action'] == 'pd_probe' and pd['state'] == 'offered' and pd['prefix'] == '2001:db8::'
      and pd['prefix_len'] == 60 and pd['valid_s'] == 3600 and pd['server'] == 'fe80::1', f'offered {r}')
check(len(calls) == 1 and calls[0][0] == 'wlan0' and calls[0][1][0] == 1, 'one SOLICIT on the interface')

stub(lambda xid: (reply(ia_pd(opt(13, b'\x00\x06')), xid=xid), 'fe80::1'))
pd = helper.dhcpv6_pd_probe()['pd']
check(pd['state'] == 'not_offered' and 'NoPrefixAvail' in pd['detail'], f'NoPrefixAvail {pd}')

calls.clear()
stub(None)
pd = helper.dhcpv6_pd_probe()['pd']
check(pd['state'] == 'not_offered' and 'No DHCPv6 server answered' in pd['detail'], f'silence {pd}')
check(len(calls) == helper.PD_ATTEMPTS and sum(c[2] for c in calls) <= 12.0, 'bounded retries')

stub(lambda xid: (b'\x02\x00', 'fe80::1'))
check(helper.dhcpv6_pd_probe()['pd']['state'] == 'not_offered', 'garbage answer is not an offer')

stub(OSError(1, 'Operation not permitted'))
pd = helper.dhcpv6_pd_probe()['pd']
check(pd['state'] == 'unavailable' and 'Operation not permitted' in pd['detail'], f'socket error {pd}')

stub(None)
(tmp / 'sys' / 'wlan0' / 'operstate').write_text('down\n')
check(helper.dhcpv6_pd_probe()['pd']['state'] == 'unavailable', 'interface down')
(tmp / 'sys' / 'wlan0' / 'operstate').write_text('up\n')
inet6.write_text('')
check(helper.dhcpv6_pd_probe()['pd']['state'] == 'unavailable', 'no link-local')
check(helper.dhcpv6_pd_probe('wlan9')['pd']['state'] == 'unavailable', 'missing interface')
helper.PD_EUID = lambda: 1000
calls.clear()
check(helper.dhcpv6_pd_probe()['pd']['state'] == 'unavailable' and not calls, 'not root sends nothing')

# CLI dispatch: the unprivileged refusal runs through the EUID seam, so it is
# exercised whether or not the suite itself runs as root (the same gate is also
# pinned for scan/action in tests/privilege-gate.py).
import contextlib
import io
real_euid, real_argv = helper.EUID, sys.argv
try:
    helper.EUID = lambda: 1000
    sys.argv = ['travelpi-cockpit', 'pd']
    calls.clear()
    stub(None)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = helper.main()
    payload = json.loads(out.getvalue())
    check(payload.get('error', {}).get('code') == 'not_privileged' and code == 1, f'cli pd unprivileged {payload}')
    check(not calls, 'the pd refusal must not send a SOLICIT')
finally:
    helper.EUID, sys.argv = real_euid, real_argv

if failures:
    print('pd probe FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('pd probe checks passed')
