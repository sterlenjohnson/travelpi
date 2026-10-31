#!/usr/bin/env python3
"""Packaging allowlist, PI_USER validation and restore allowlist guards.

`make package-list` must emit only what deploy installs: never backups (hotel
PSKs, tailnet key), node_modules, tool logs, local notes or git data. The list
is checked in a scratch git repo seeded with decoys, then against the real tree.
`make check-pi-user` guards the sudoers line. RESTORE_PATHS must cover every
member the backup script archives.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
MAKE = MAKEFILE.read_text(encoding="utf-8")
failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


def deploy_sources():
    start = MAKE.find("\ndeploy:")
    block = MAKE[start:]
    nxt = re.search(r"\n[hA-Za-z0-9_-]+:", block[1:])
    block = block[:nxt.start() + 1] if nxt else block

    def expand(m):
        var, items, body = m.group(1), m.group(2).split(), m.group(3)
        out = []
        for item in items:
            r = body
            for form in ("$" + "$" + var, "${" + var + "}", "$" + var):
                r = r.replace(form, item)
            out.append(r)
        return " ; ".join(out)

    block = re.sub(r"for\s+(\w+)\s+in\s+([^;]+);\s*do\s*(.*?)\s*;\s*done", expand, block)
    prefix = "$" + "$W/"
    return sorted({r for r in re.findall(re.escape(prefix) + r"([A-Za-z0-9._/-]+)", block)
                   if r and not r.endswith("/") and not r.startswith("sudoers.")})


def run_list(cwd, out):
    return subprocess.run(["make", "-s", "-f", str(MAKEFILE), "-C", str(cwd), "package-list",
                           f"PACKAGE_LIST={out}"], capture_output=True, text=True)


FORBIDDEN = re.compile(r"(^|/)(backups|node_modules|\.playwright-mcp|\.opencode|\.git|__pycache__|tests|docs)(/|$)"
                       r"|\.DS_Store|\.local\.md$|\.tar\.gz$")
sources = deploy_sources()
check(len(sources) > 15, f"deploy source parse failed ({len(sources)})")

# 1. scratch repo with decoys
with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    scratch = tmp / "repo"
    for rel in sources + ["backups/config-1.tar.gz", "node_modules/x/index.js", ".playwright-mcp/a.log",
                          ".DS_Store", "systemd/.DS_Store", "notes.local.md", "systemd/x.local.md",
                          ".opencode/s.json", "tests/t.py", "docs/a.md", "helper/__pycache__/h.pyc",
                          "prototype-travelpi-glinet.html", "dist/old.tar.gz"]:
        f = scratch / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x")
    subprocess.run(["git", "init", "-q"], cwd=scratch, check=True)
    out = tmp / "list.txt"
    r = run_list(scratch, out)
    check(r.returncode == 0, f"package-list failed in scratch repo: {r.stderr}")
    listed = out.read_text().split("\n") if out.exists() else []
    listed = [x for x in listed if x]
    bad = [x for x in listed if FORBIDDEN.search(x)]
    check(not bad, f"package list contains forbidden paths: {bad}")
    check("prototype-travelpi-glinet.html" not in listed, "prototype page must not ship")
    missing = [s for s in sources if s not in listed]
    check(not missing, f"package list misses deploy-installed files: {missing}")

# 2. real tree
with tempfile.TemporaryDirectory() as tmp:
    out = Path(tmp) / "list.txt"
    r = run_list(ROOT, out)
    check(r.returncode == 0, f"package-list failed on real tree: {r.stderr}")
    listed = [x for x in out.read_text().split("\n") if x]
    check(not [x for x in listed if FORBIDDEN.search(x)], "real tree list has forbidden paths")
    check(not [s for s in sources if s not in listed], "real tree list misses deploy files")

# 3. PI_USER validation
def pi_user(value):
    return subprocess.run(["make", "-s", "-f", str(MAKEFILE), "check-pi-user", f"PI_USER={value}"],
                          capture_output=True, text=True, cwd=ROOT).returncode

for good in ("pi", "sterl", "_svc", "a-b_c9"):
    check(pi_user(good) == 0, f"PI_USER {good!r} should be accepted")
for bad in ("Pi", "9pi", "a b", "a;rm", "a$$(id)", "", "-x", "a\"b", "a'b"):
    check(pi_user(bad) != 0, f"PI_USER {bad!r} should be rejected")
check("check-pi-user" in re.search(r"\ndeploy:[^\n]*", MAKE).group(0), "deploy must depend on check-pi-user")
check("check-pi-user" in re.search(r"\nrestore:[^\n]*", MAKE).group(0), "restore must depend on check-pi-user")

# 4. sudoers is validated before it reaches /etc/sudoers.d
check("visudo -cf $$W/sudoers.new" in MAKE, "sudoers must be validated on a temp file")
check(MAKE.find("visudo -cf") < MAKE.find("/etc/sudoers.d/travelpi-adguard"), "visudo must precede install into sudoers.d")
check("tee /etc/sudoers.d" not in MAKE, "no direct write into /etc/sudoers.d")

# 5. restore allowlist covers the backup archive list
backup = (ROOT / "systemd" / "travelpi-config-backup").read_text(encoding="utf-8")
tar_block = backup[backup.index("# BEGIN BACKUP PATHS"):backup.index("# END BACKUP PATHS")]
members = re.findall(r"^((?:etc|usr|var)/[A-Za-z0-9._/-]+)\s*$", tar_block, re.M)
members.append("etc/travelpi-AdGuardHome.yaml")
paths_block = MAKE[MAKE.index("RESTORE_PATHS :="):MAKE.index("RESTORE_CASE")]
paths = set(re.findall(r"(?:etc|usr|var)/[A-Za-z0-9._/-]+", paths_block))
check(len(members) > 15, "failed to parse backup tar members")
check(set(members) <= paths, f"restore allowlist misses backup members: {sorted(set(members) - paths)}")
check(paths <= set(members), f"restore allowlist has paths the backup never writes: {sorted(paths - set(members))}")
check("CONFIRM" in MAKE and "tar -tzf" in MAKE, "restore must list and require CONFIRM")
rest = MAKE[MAKE.index("\nrestore:"):MAKE.index("\nharness-status")]
check("/tmp/travelpi-restore" not in rest and "mktemp -d" in rest, "restore must use a private temp dir")

# 5b. deploy guards: a failed extract, missing sudo or missing core files abort before any install
dep = MAKE[MAKE.index("\ndeploy:"):MAKE.index("\nimage-update") if "\nimage-update" in MAKE else len(MAKE)]
first_install = dep.find("sudo install")
for guard in ('|| { echo "extract failed"; exit 1; }', "exec </dev/null", 'sudo -n true || { echo "passwordless sudo required"; exit 1; }',
              "test -f $$W/helper/travelpi-cockpit", "test -f $$W/manifest.json"):
    check(0 <= dep.find(guard) < first_install, f"deploy guard must precede the first sudo install: {guard}")
check("tar -xzf - -C $$W &&" not in dep, "tar extraction must not be chained with && into installs")
check('core install failed; aborting before restarts' in dep, "core install chain must abort before restarts")
check(dep.find("core install failed") < dep.find("systemctl restart wlan1-static-ip"), "abort guard must precede first restart")
check('test "$(RADIO_SWITCH)" = 1; then sudo /usr/local/libexec/travelpi-radio-driver' in dep, "live radio switch must be opt-in")
check("RADIO_SWITCH ?= 0" in MAKE, "RADIO_SWITCH default missing")
check("visudo -cf /etc/sudoers.d/travelpi-adguard" in MAKE[MAKE.index("\nrestore:"):], "restore must validate the extracted sudoers member")
check("sudo sh -c 'chmod 600 /etc/NetworkManager/system-connections/*.nmconnection'" in MAKE, "restore chmod glob must expand under sudo")

# 6. opt-ins
check('test "$(DISABLE_UNUSED_SERVICES)" = 1; then sudo systemctl disable --now exim4' in MAKE, "exim4/containerd disable must be opt-in")
check("SKIP_NM_RESTART" in MAKE and 'SKIP_NM_RESTART ?= 0' in MAKE, "SKIP_NM_RESTART missing")

if failures:
    print("package list guard FAILED:")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print(f"package list guard checks passed ({len(sources)} deploy files, {len(paths)} restore paths)")
