#!/usr/bin/env python3
import importlib.machinery
import importlib.util
from pathlib import Path

path = Path(__file__).parents[1] / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

tailscale = helper.parse_tailscale_status({
    'BackendState': 'Running',
    'Self': {'TailscaleIPs': ['100.64.0.2', 'fd7a::2']},
    'ExitNodeStatus': {'ID': 'node-a', 'HostName': 'exit-a', 'Online': True},
    'Peer': {'key-a': {'Relay': ''}, 'key-b': {'Relay': 'nyc'}},
})
assert tailscale['state'] == 'Running'
assert tailscale['addresses'] == ['100.64.0.2', 'fd7a::2']
assert tailscale['peer_count'] == 2
assert tailscale['exit_node'] == 'exit-a'
assert tailscale['exit_node_active'] is True
assert tailscale['transport'] == 'relay'
assert helper.parse_tailscale_status({'BackendState': 'Stopped', 'Self': {'TailscaleIPs': None}})['addresses'] == []

wireguard = helper.parse_wireguard_dump(
    'private\tpublic\t51820\n'
    'peer-a\tpsk\t198.51.100.4:51820\t10.0.0.0/24\t1700000000\t0\t0\t1420\n'
)
assert wireguard['state'] == 'active'
assert wireguard['peer_count'] == 1
assert wireguard['routes'] == ['10.0.0.0/24']
assert wireguard['endpoints'] == ['198.51.100.4:51820']
assert wireguard['latest_handshake'] == 1700000000

assert helper.parse_wireguard_dump('')['state'] == 'inactive'
print('vpn status checks passed')
