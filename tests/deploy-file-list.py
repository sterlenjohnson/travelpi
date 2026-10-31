#!/usr/bin/env python3
"""Packaging contract: `make deploy` installs exactly the files this repo ships.

The deploy target is one long ssh command; nothing else checked that its install
list matches the tree. This guard expands the shell `for` loops, then asserts:
every source path deploy reads out of the unpacked archive exists, every file
under systemd/ is installed (or named in the README as host-side), and every
installed unit is enabled, started, or driven by an enabled sibling timer.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKE = (ROOT / "Makefile").read_text(encoding="utf-8")
PREFIX = "$" + "$W/"

failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


deploy_start = MAKE.find("\ndeploy:")
check(deploy_start >= 0, "Makefile must define deploy")
if failures:
    sys.exit(1)
deploy_block = MAKE[deploy_start:]
next_target = re.search(r"\n[hA-Za-z0-9_-]+:", deploy_block[1:])
deploy_block = deploy_block[:next_target.start() + 1] if next_target else deploy_block

# Expand each shell loop *within its own body* so `install ... $$u.slice.d/x.conf`
# is seen per unit without cross-combining separate loops. Makefile escaping
# writes `$$u` for the shell's `$u`, so both forms are expanded.
def expand_loops(text):
    def expand(match):
        var, items, body = match.group(1), match.group(2).split(), match.group(3)
        out = []
        for item in items:
            rendered = body
            for form in ("$" + "$" + var, "${" + var + "}", "$" + var):
                rendered = rendered.replace(form, item)
            out.append(rendered)
        return " ; ".join(out)

    return re.sub(r"for\s+(\w+)\s+in\s+([^;]+);\s*do\s*(.*?)\s*;\s*done", expand, text)


expanded = expand_loops(deploy_block)

sources = sorted({rel for rel in re.findall(re.escape(PREFIX) + r"([A-Za-z0-9._/-]+)", expanded)
                  if rel and not rel.endswith("/")})
check(len(sources) > 15, f"expected the deploy install list to parse, got {len(sources)} paths")

# $W/sudoers.* are scratch files the recipe writes itself, not archive members.
sources = [rel for rel in sources if not rel.startswith("sudoers.")]
missing = [rel for rel in sources if not (ROOT / rel).exists()]
check(not missing, f"deploy installs files that are not in the repo: {missing}")

# Every file under systemd/ must be installed by deploy, or named in the README
# as host-side configuration the administrator owns.
readme = (ROOT / "README.md").read_text(encoding="utf-8")
installed = set(sources)
orphans = []
for path in sorted((ROOT / "systemd").rglob("*")):
    if path.is_dir() or path.name.startswith("."):
        continue
    rel = str(path.relative_to(ROOT))
    if rel in installed:
        continue
    if path.name in readme:
        continue
    orphans.append(rel)
check(not orphans, f"files under systemd/ that deploy never installs and README never names: {orphans}")

# Installed units must be enabled/reenabled, started by deploy, or driven by an
# enabled sibling timer (travelpi-sqm-tune.service is timer-driven by design).
enabled, started = set(), set()
for verb, names in re.findall(r"systemctl\s+((?:enable|reenable|start)(?:\s+--now)?)\s+([A-Za-z0-9._ ${}-]+)", expanded):
    for name in names.split():
        (started if verb.startswith("start") else enabled).add(name)

for rel in sources:
    if not rel.endswith((".service", ".timer")):
        continue
    unit = Path(rel).name
    if unit in enabled or unit in started:
        continue
    stem = unit.split(".")[0]
    check(stem + ".timer" in enabled,
          f"{unit}: installed by deploy but never enabled, reenabled, started, or driven by {stem}.timer")

if failures:
    print("deploy file list guard FAILED:")
    for item in failures:
        print(f"  - {item}")
    sys.exit(1)
print(f"deploy file list guard checks passed ({len(sources)} installed paths, "
      f"{len(enabled)} enabled, {len(started)} started)")
