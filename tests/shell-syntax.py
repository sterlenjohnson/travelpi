#!/usr/bin/env python3
"""Every shell script the repo ships parses: `sh -n` / `bash -n` over each file
under systemd/ and reset-travelpi-radios.sh whose shebang names sh or bash
(chosen by the shebang, so a bashism in a #!/bin/sh script is caught on hosts
whose sh is dash). The set is discovered, not listed, so a new script is
covered on arrival; a script without a shebang is reported, not skipped."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
failures = []
checked = []


def check(cond, label):
    if not cond:
        failures.append(label)


candidates = [ROOT / 'reset-travelpi-radios.sh']
candidates += sorted(p for p in (ROOT / 'systemd').rglob('*') if p.is_file() and not p.name.startswith('.'))
for path in candidates:
    rel = path.relative_to(ROOT)
    try:
        first = path.read_text(encoding='utf-8').split('\n', 1)[0]
    except UnicodeDecodeError:
        continue
    if not first.startswith('#!'):
        # units, drop-ins, confs, .network files: not scripts. A *.sh without a shebang is a mistake.
        check(path.suffix != '.sh', f'{rel}: shell script without a shebang')
        continue
    words = first[2:].split()
    interpreter = Path(words[0]).name if words else ''
    if interpreter == 'env' and len(words) > 1:
        interpreter = words[1]
    if interpreter not in ('sh', 'bash', 'dash'):
        continue
    # #!/bin/sh scripts are checked with dash (the Pi's /bin/sh) when installed.
    shell = 'bash' if interpreter == 'bash' else ('dash' if shutil.which('dash') else 'sh')
    check(shutil.which(shell) is not None, f'{shell} is required to check {rel}')
    result = subprocess.run([shell, '-n', str(path)], capture_output=True, text=True)
    check(result.returncode == 0, f'{rel}: {shell} -n failed: {result.stderr.strip()}')
    checked.append(str(rel))

check(len(checked) >= 10, f'expected to discover the shipped scripts, found {len(checked)}: {checked}')
for must in ('reset-travelpi-radios.sh', 'systemd/travelpi-radio-watch', 'systemd/travelpi-mem-watch',
             'systemd/travelpi-ap-ip', 'systemd/travelpi-adguard-hotel-dns', 'systemd/travelpi-radio-driver'):
    check(must in checked, f'{must} must be covered by the syntax loop')

if failures:
    print('shell syntax FAILED:')
    for item in failures:
        print('  -', item)
    sys.exit(1)
print(f'shell syntax checks passed ({len(checked)} scripts)')
