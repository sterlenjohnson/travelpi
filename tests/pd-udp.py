#!/usr/bin/env python3
"""pd_udp_exchange against real loopback UDP sockets.

The helper opens its sockets through the PD_SOCKETS seam; the test hands it a
loopback pair instead of the privileged raw/multicast pair (the raw side is a
real UDP socket wrapped to prepend the UDP header a raw IPPROTO_UDP read
carries). Pinned: silence returns None after the timeout, a datagram with the
wrong xid (or wrong ports) is ignored, a correct reply is returned with its
source, and every socket is closed on every path, including a failing send and
a failing second socket open (no ResourceWarning).
"""
import errno
import gc
import importlib.machinery
import importlib.util
import socket
import sys
import threading
import time
import warnings
from pathlib import Path

warnings.simplefilter('error', ResourceWarning)

path = Path(__file__).parents[1] / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


XID = b'\x0a\x0b\x0c'
OTHER_XID = b'\x01\x02\x03'


def dhcp_reply(xid):
    return bytes([2]) + xid + (13).to_bytes(2, 'big') + (2).to_bytes(2, 'big') + b'\x00\x06'


def udp_header(sport, dport, payload):
    return sport.to_bytes(2, 'big') + dport.to_bytes(2, 'big') + (8 + len(payload)).to_bytes(2, 'big') + b'\0\0' + payload


class RawLike:
    """Real UDP socket that prepends a UDP header on recvfrom, like a raw read.
    The header ports come from a one-shot queue so a test can send bad ones."""

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', 0))
        self.address = self.sock.getsockname()

    def fileno(self):
        return self.sock.fileno()

    def recvfrom(self, size):
        data, source = self.sock.recvfrom(size)
        # the responder encodes the ports it wants in a 4 byte prefix
        sport, dport = int.from_bytes(data[:2], 'big'), int.from_bytes(data[2:4], 'big')
        return udp_header(sport, dport, data[4:]), source

    def close(self):
        self.sock.close()


class Setup:
    """A responder thread plus the socket pair PD_SOCKETS hands out."""

    def __init__(self, replies, send_raises=False):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server.bind(('127.0.0.1', 0))
        self.server.settimeout(5)
        self.raw = RawLike()
        self.sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.send_raises = send_raises
        self.replies = replies  # list of (sport, dport, payload)
        self.received = []
        self.thread = threading.Thread(target=self.respond, daemon=True)
        self.thread.start()

    def respond(self):
        try:
            data, _ = self.server.recvfrom(2048)
        except OSError:
            return
        self.received.append(data)
        for sport, dport, payload in self.replies:
            self.server.sendto(sport.to_bytes(2, 'big') + dport.to_bytes(2, 'big') + payload, self.raw.address)

    def sockets(self, interface):
        self.interface = interface
        if self.send_raises:
            self.sender.close()  # sendto on a closed socket raises OSError
        return self.raw, self.sender, self.server.getsockname()

    def closed(self):
        return self.raw.sock.fileno() == -1 and self.sender.fileno() == -1

    def finish(self):
        self.thread.join(timeout=5)
        self.server.close()


def exchange(replies, timeout=0.6, send_raises=False):
    setup = Setup(replies, send_raises=send_raises)
    helper.PD_SOCKETS = setup.sockets
    started = time.monotonic()
    error = None
    got = None
    try:
        got = helper.pd_udp_exchange('wlan0', b'SOLICIT-BYTES', XID, timeout)
    except OSError as exc:
        error = exc
    elapsed = time.monotonic() - started
    setup.finish()
    return setup, got, error, elapsed


with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always')
    real_sockets = helper.PD_SOCKETS
    try:
        # --- silence: None after about the timeout, sockets closed, the solicit was sent.
        setup, got, error, elapsed = exchange([], timeout=0.4)
        check(got is None and error is None, 'silence must return None: %r %r' % (got, error))
        check(0.3 <= elapsed < 10, 'silence must wait about the timeout, took %.2fs' % elapsed)
        check(setup.received == [b'SOLICIT-BYTES'], 'the SOLICIT must be sent verbatim to the destination: %s' % setup.received)
        check(setup.interface == 'wlan0', 'sockets must be opened for the requested interface')
        check(setup.closed(), 'silence: sockets must be closed')

        # --- a reply for another transaction is ignored (and does not end the wait early).
        setup, got, error, elapsed = exchange([(547, 546, dhcp_reply(OTHER_XID))], timeout=0.5)
        check(got is None, 'a wrong-xid reply must be ignored: %r' % (got,))
        check(elapsed >= 0.4, 'a wrong-xid reply must not end the wait early (%.2fs)' % elapsed)
        check(setup.closed(), 'wrong xid: sockets must be closed')

        # --- wrong UDP ports are ignored even with the right xid.
        setup, got, error, elapsed = exchange([(53, 546, dhcp_reply(XID)), (547, 1000, dhcp_reply(XID))], timeout=0.5)
        check(got is None, 'a datagram not from 547 to 546 must be ignored: %r' % (got,))
        check(setup.closed(), 'wrong ports: sockets must be closed')

        # --- wrong xid first, then the right one: the right one is returned.
        replies = [(547, 546, dhcp_reply(OTHER_XID)), (547, 546, dhcp_reply(XID))]
        setup, got, error, elapsed = exchange(replies, timeout=8.0)
        check(got is not None and got[0] == dhcp_reply(XID), 'the matching reply must be returned: %r' % (got,))
        check(got is not None and got[1] == '127.0.0.1', 'the source address must be returned: %r' % (got,))
        check(elapsed < 7.5, 'a matching reply must return promptly (%.2fs)' % elapsed)
        check(setup.closed(), 'reply: sockets must be closed')
        # and it parses as the answer to our transaction
        check(got and helper.parse_pd_reply(got[0], XID) is not None and helper.parse_pd_reply(got[0], OTHER_XID) is None,
              'the returned payload must belong to our xid')

        # --- a failing send raises OSError and still closes everything.
        setup, got, error, elapsed = exchange([], send_raises=True)
        check(isinstance(error, OSError) and got is None, 'a send failure must raise OSError: %r %r' % (got, error))
        check(setup.closed(), 'send failure: sockets must be closed')

        # --- the real opener closes the first socket when the second cannot be created.
        helper.PD_SOCKETS = real_sockets
        made = []
        real_socket_class, real_index = socket.socket, socket.if_nametoindex

        class Tracked(real_socket_class):
            pass

        def factory(family, kind, *args):
            if len(made) == 1:
                raise OSError(errno.EMFILE, 'too many open files')
            sock = Tracked(socket.AF_INET, socket.SOCK_DGRAM)
            made.append(sock)
            return sock

        socket.socket = factory
        socket.if_nametoindex = lambda interface: 1
        try:
            try:
                helper.pd_open_sockets('wlan0')
                check(False, 'a failing second socket must raise')
            except OSError as exc:
                check(exc.errno == errno.EMFILE, 'the original error must propagate: %r' % exc)
        finally:
            socket.socket, socket.if_nametoindex = real_socket_class, real_index
        check(len(made) == 1 and made[0].fileno() == -1, 'the first socket must be closed when the second open fails')
    finally:
        helper.PD_SOCKETS = real_sockets
    gc.collect()
    leaked = [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]
    check(not leaked, 'ResourceWarning: sockets leaked: %s' % leaked)

if failures:
    print('pd udp FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print('pd udp checks passed')
