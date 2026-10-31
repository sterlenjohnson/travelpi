#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

root = Path(__file__).parents[1]
path = root / 'helper' / 'travelpi-cockpit'
loader = importlib.machinery.SourceFileLoader('travelpi_helper', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
helper = importlib.util.module_from_spec(spec)
loader.exec_module(helper)

assert helper.sqm_environment('30Mbit') == 'TRAVELPI_SQM_RATE=30Mbit\nTRAVELPI_SQM_AUTOTUNE=no\n'
assert helper.parse_rate('30Mbps') == (30000, '30000kbit')
assert helper.parse_rate('12500kbit') == (12500, '12500kbit')

# auto-tune status: sandboxed state + env files
sandbox = tempfile.mkdtemp(prefix='travelpi-sqm-')
helper.SQM_ENV_FILE = os.path.join(sandbox, 'sqm-env')
helper.SQM_AUTOTUNE_STATE = os.path.join(sandbox, 'sqm-autotune.json')
assert helper.sqm_autotune_status() == {'mode': 'auto', 'state': 'off'}
with open(helper.SQM_AUTOTUNE_STATE, 'w') as fh:
    json.dump({'ts': time.time() - 3600, 'down_mbit': 40, 'up_mbit': 20,
               'applied_down_mbit': 36, 'applied_up_mbit': 18, 'adopted': True}, fh)
status = helper.sqm_autotune_status()
assert status['state'] == 'active', status
assert status['applied_down_mbit'] == 36 and status['applied_up_mbit'] == 18
with open(helper.SQM_ENV_FILE, 'w') as fh:
    fh.write('TRAVELPI_SQM_RATE=12Mbit\nTRAVELPI_SQM_AUTOTUNE=no\n')
assert helper.sqm_autotune_status()['state'] == 'pinned'
with open(helper.SQM_AUTOTUNE_STATE, 'w') as fh:
    json.dump({'ts': time.time() - 8 * 3600, 'down_mbit': 40, 'up_mbit': 20,
               'applied_down_mbit': 36, 'applied_up_mbit': 18, 'adopted': True}, fh)
os.remove(helper.SQM_ENV_FILE)
assert helper.sqm_autotune_status()['state'] == 'stale'
with open(helper.SQM_AUTOTUNE_STATE, 'w') as fh:
    json.dump({'ts': time.time(), 'last_error': 'probe_failed'}, fh)
assert helper.sqm_autotune_status()['state'] == 'probe-failed'

# tuner script: sandboxed probes, smoothing, and the pin opt-out
script = root / 'systemd' / 'travelpi-sqm-autotune'
tune_env = dict(os.environ,
               TRAVELPI_AUTOTUNE_STATE_DIR=sandbox,
               TRAVELPI_AUTOTUNE_ENV=os.path.join(sandbox, 'tune-env'),
               TRAVELPI_AUTOTUNE_NO_APPLY='1',
               TRAVELPI_AUTOTUNE_PROBE_DOWN='5000000',   # 40 Mbit
               TRAVELPI_AUTOTUNE_PROBE_UP='2500000')     # 20 Mbit
with open(tune_env['TRAVELPI_AUTOTUNE_ENV'], 'w') as fh:
    fh.write('TRAVELPI_SQM_RATE=12Mbit\n')
os.remove(helper.SQM_AUTOTUNE_STATE)
subprocess.run(['sh', str(script)], env=tune_env, check=True)
state = Path(tune_env['TRAVELPI_AUTOTUNE_ENV']).read_text()
assert 'TRAVELPI_SQM_RATE=18Mbit' in state, state          # 90% of 20 Mbit
assert 'TRAVELPI_SQM_RATE_DOWN=36Mbit' in state, state     # 90% of 40 Mbit
assert 'TRAVELPI_SQM_AUTOTUNE=yes' in state, state
env_text = Path(tune_env['TRAVELPI_AUTOTUNE_ENV']).read_text()
helper.SQM_AUTOTUNE_STATE = os.path.join(sandbox, 'sqm-autotune.json')
assert helper.sqm_autotune_status()['state'] == 'active'
# identical measurement: below the 15% bar, rates stay
subprocess.run(['sh', str(script)], env=tune_env, check=True)
assert Path(tune_env['TRAVELPI_AUTOTUNE_ENV']).read_text() == env_text
assert json.loads(Path(helper.SQM_AUTOTUNE_STATE).read_text())['adopted'] is False
# 20% slower down: adopted
subprocess.run(['sh', str(script)], env=dict(tune_env, TRAVELPI_AUTOTUNE_PROBE_DOWN='3500000'), check=True)
state = Path(tune_env['TRAVELPI_AUTOTUNE_ENV']).read_text()
assert 'TRAVELPI_SQM_RATE_DOWN=25Mbit' in state, state  # 90% of 28 Mbit
assert 'TRAVELPI_SQM_RATE=18Mbit' in state, state
# pinned: tuner declines to run at all
with open(tune_env['TRAVELPI_AUTOTUNE_ENV'], 'w') as fh:
    fh.write('TRAVELPI_SQM_RATE=25Mbit\nTRAVELPI_SQM_AUTOTUNE=no\n')
pinned_text = Path(tune_env['TRAVELPI_AUTOTUNE_ENV']).read_text()
subprocess.run(['sh', str(script)], env=tune_env, check=True)
assert Path(tune_env['TRAVELPI_AUTOTUNE_ENV']).read_text() == pinned_text
# weak probe with prior state: keep working schedule
shutil.rmtree(sandbox)

print('SQM persistence checks passed')
