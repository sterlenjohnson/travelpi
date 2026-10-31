#!/usr/bin/env python3
"""Guard for systemd/travelpi-config-backup and its Makefile pull target.

The backup archive contains hotel PSKs, the tailnet node key, and the AdGuard
admin hash, so the contract is: the archive is root-only, the backup directory
stays listable (the login user must find the newest filename), and rotation
keeps the newest archives instead of deleting the one just written.

The script is run for real in a sandbox with a `tar` shim on PATH, because the
development host ships bsdtar, which rejects GNU's --ignore-failed-read. The
shim records the invocations; every assertion below is about observable files,
modes, and the rotation outcome.
"""
import os
os.environ["TRAVELPI_TEST"] = "1"  # enable script path overrides (test seam)
import re
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "systemd" / "travelpi-config-backup"
MAKEFILE = ROOT / "Makefile"

failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


def dir_mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def run_backup(sandbox, home):
    env = dict(os.environ)
    env["PATH"] = str(sandbox / "bin") + os.pathsep + env["PATH"]
    env["TRAVELPI_BACKUP_DIR"] = str(sandbox / "backups")
    env["TRAVELPI_BACKUP_KEEP"] = "2"
    proc = subprocess.run(
        ["/bin/sh", str(SCRIPT)],
        env=env,
        cwd=str(home),
        capture_output=True,
        text=True,
    )
    check(proc.returncode == 0, f"script exited {proc.returncode}: {proc.stderr.strip()}")
    return proc


def main():
    sandbox = Path(os.environ.get("TMPDIR", "/tmp")) / "travelpi-config-backup-sandbox"
    if sandbox.exists():
        subprocess.run(["/bin/rm", "-rf", str(sandbox)], check=True)
    (sandbox / "bin").mkdir(parents=True)
    home = sandbox / "home"
    home.mkdir(parents=True)
    out = sandbox / "backups"

    # tar shim: accepts the script's create/append forms and records them.
    shim = sandbox / "bin" / "tar"
    shim.write_text(
        "#!/bin/sh\n"
        'echo "tar $*" >> "$TAR_SHIM_LOG"\n'
        'case "$1" in\n'
        '  -czf*) : > "$2" ;;\n'
        "esac\n"
        'exit "${TAR_SHIM_RC:-0}"\n'
    )
    shim.chmod(0o755)
    log = sandbox / "tar-shim.log"
    os.environ["TAR_SHIM_LOG"] = str(log)

    proc = run_backup(sandbox, home)
    check(proc.returncode == 0, "first run must succeed")

    archives = sorted(out.glob("config-*.tar.gz"))
    check(len(archives) == 1, f"first run must leave exactly 1 archive, got {len(archives)}")
    check(dir_mode(out) == 0o755, f"backup dir must stay listable 0755, got {oct(dir_mode(out))}")
    if archives:
        check(
            dir_mode(archives[0]) == 0o600,
            f"archive must be root-only 0600, got {oct(dir_mode(archives[0]))}",
        )

    # The staged AdGuard copy must be appended into the archive, not dropped.
    shim_log = log.read_text() if log.exists() else ""
    check("-czf" in shim_log, "shim must record the create invocation")
    check("-rzf" not in shim_log, "tar -r cannot append to a gzip archive; stage before the single create")
    check("travelpi-AdGuardHome.yaml" in shim_log, "AdGuard stage must be part of the create invocation")
    check(not list(out.glob(".stage.*")), "stage dir must be cleaned up")

    # ADR 0003 scope: the archive carries the whole hand-built config set, and
    # the path list lives in one delimited block that `make restore` can read.
    expected = [
        "etc/NetworkManager/system-connections", "etc/hostapd/hostapd.conf",
        "etc/dnsmasq.d/travelpi.conf", "etc/default/travelpi-dns",
        "etc/default/travelpi-power-profile", "etc/default/travelpi-sqm",
        "etc/unbound/unbound.conf.d/travelpi-front.conf",
        "etc/systemd/network/070-travelpi-ap.network",
        "etc/systemd/network/070-travelpi-ap.network.d",
        "etc/travelpi-home-dns", "etc/travelpi", "var/lib/tailscale",
    ]
    tar_args = [line for line in shim_log.splitlines() if line.startswith("tar -czf")]
    check(len(tar_args) >= 1, "shim must have recorded a create invocation")
    words = tar_args[0].split() if tar_args else []
    for path in expected:
        check(path in words, f"archive must include {path}")
    check("--ignore-failed-read" in words, "missing optional paths must not fail the backup")
    check("etc/travelpi/ula-prefix" not in words,
          "etc/travelpi is archived as a directory, not just the ula-prefix file")
    script_text = SCRIPT.read_text()
    block = re.search(r"# BEGIN BACKUP PATHS\nBACKUP_PATHS='\n(.*?)'\n# END BACKUP PATHS", script_text, re.S)
    check(block is not None, "the path list must sit in a BEGIN/END BACKUP PATHS block")
    if block:
        listed = block.group(1).split()
        check(all(not path.startswith("/") for path in listed), "listed paths must be relative to /")
        check(all(path in words for path in listed), "every listed path must reach tar")
        check(len(listed) == len(set(listed)), "the path list must not repeat entries")
        check("etc/hostapd/hostapd.conf" in listed and "etc/travelpi-home-dns" in listed,
              "the block must be the single source of the archived paths")

    # Rotation: seed older archives, run again, and require the newest to
    # survive. Plain `tail -n N` deletes everything including the new file.
    newest = archives[0]
    older_names = [
        out / "config-20260101T000000Z.tar.gz",
        out / "config-20260102T000000Z.tar.gz",
        out / "config-20260103T000000Z.tar.gz",
    ]
    base = 1_700_000_000
    for i, name in enumerate(older_names):
        name.write_bytes(b"seed")
        name.chmod(0o600)
        os.utime(name, (base + i, base + i))
    os.utime(newest, (base + 100, base + 100))

    run_backup(sandbox, home)
    after = sorted(out.glob("config-*.tar.gz"))
    survivors = {p.name for p in after}
    check(len(after) == 2, f"rotation must keep KEEP=2 archives, got {len(after)}: {sorted(survivors)}")
    check(newest.name in survivors, f"rotation deleted the archive just written: {sorted(survivors)}")
    check(older_names[0] not in survivors and older_names[1] not in survivors,
          f"rotation must delete the oldest seeds, survivors: {sorted(survivors)}")
    for p in after:
        check(dir_mode(p) == 0o600, f"every surviving archive must be 0600, {p.name} is {oct(dir_mode(p))}")

    # tar exit 1 (file changed while read) is a warning that keeps the archive;
    # exit 2 is fatal and leaves no archive behind.
    def run_with_rc(rc):
        env = dict(os.environ, TAR_SHIM_RC=str(rc), TRAVELPI_BACKUP_KEEP="50",
                   PATH=str(sandbox / "bin") + os.pathsep + os.environ["PATH"],
                   TRAVELPI_BACKUP_DIR=str(sandbox / "backups"))
        before = set(out.glob("config-*.tar.gz"))
        proc = subprocess.run(["/bin/sh", str(SCRIPT)], env=env, cwd=str(home), capture_output=True, text=True)
        return proc, set(out.glob("config-*.tar.gz")) - before
    import time
    time.sleep(1.1)  # distinct timestamp stamp from the earlier run
    proc1, new1 = run_with_rc(1)
    check(proc1.returncode == 0 and len(new1) == 1, "tar exit 1 must be a warning that keeps the archive")
    time.sleep(1.1)
    proc2, new2 = run_with_rc(2)
    check(proc2.returncode == 2 and not new2, "tar exit 2 must fail the backup and remove the archive")

    # Static contract on the pull target: the login user cannot read a 0600
    # root archive, so the pull must go through sudo; it runs over a PTY so
    # sudo can prompt, which rewrites newlines, so the archive must travel
    # base64-encoded and be verified after decoding.
    make = MAKEFILE.read_text()
    pull = re.search(r"^backup-pull:$", make, re.M)
    check(pull is not None, "Makefile must define backup-pull")
    if pull:
        block = make[pull.start():]
        block = block.split("\n\n")[0]
        check("sudo base64" in block, "backup-pull must read the 0600 archive through sudo")
        check("scp" not in block, "backup-pull must not scp a root-only archive as the login user")
        check("base64 -D" in block, "backup-pull must decode the base64 stream (a PTY rewrites newlines)")
        check("tar -tzf" in block, "backup-pull must verify the decoded archive is a readable tarball")
        check("sudo cat" not in block,
              "backup-pull must not pipe raw gzip through a PTY: 0x0A becomes 0x0D 0x0A and corrupts it")
        check("chmod 600 \"backups/" in block, "backup-pull must land the local copy 0600")

    if failures:
        print("config backup guard FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("config backup guard checks passed")


if __name__ == "__main__":
    main()
