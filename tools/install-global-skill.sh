#!/bin/sh
# Publish the harness2 skill to the global agent-skills directory, so every
# repository can load it.
#
#   ./tools/install-global-skill.sh            # -> ~/.agents/skills/harness2
#   ./tools/install-global-skill.sh DIR        # -> DIR/harness2
#   ./tools/install-global-skill.sh --check    # fail if the global copy drifted
#
# The repository copy (.opencode/skills/harness2) is the source of truth: edit it,
# run `python3 tests/harness2.py`, then re-run this script. It replaces only
# <destination>/harness2 and touches nothing else.

set -eu

check_only=no
if [ "${1:-}" = "--check" ]; then
    check_only=yes
    shift
fi

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir="$root/.opencode/skills/harness2"
destination_root=${1:-$HOME/.agents/skills}
destination="$destination_root/harness2"

if [ ! -f "$source_dir/SKILL.md" ]; then
    echo "error: $source_dir/SKILL.md is missing" >&2
    exit 1
fi
if [ ! -f "$source_dir/scripts/harness2.py" ]; then
    echo "error: $source_dir/scripts/harness2.py is missing" >&2
    exit 1
fi

if [ "$check_only" = yes ]; then
    if [ ! -d "$destination" ]; then
        echo "error: $destination is not installed; run ./tools/install-global-skill.sh" >&2
        exit 1
    fi
    if ! diff -r "$source_dir" "$destination" >/dev/null 2>&1; then
        echo "error: $destination has drifted from $source_dir" >&2
        diff -r "$source_dir" "$destination" | head -20 >&2
        exit 1
    fi
    echo "global skill matches $source_dir"
    exit 0
fi

mkdir -p "$destination_root"
rm -rf "$destination"
cp -R "$source_dir" "$destination"

for file in SKILL.md scripts/harness2.py reference/harness2.md; do
    if [ ! -e "$destination/$file" ]; then
        echo "error: $destination/$file did not install" >&2
        exit 1
    fi
done

echo "installed $destination"
echo "verify with: python3 $destination/scripts/harness2.py --help"
