#!/usr/bin/env python3
"""Guard the browser artifacts against module emit.

`travelpi.js` and `travelpi-typed.js` are loaded by Cockpit as classic scripts.
A TypeScript build that emits ESM or CommonJS boilerplate still parses, so the
failure only shows up in the browser. This refuses the artifact instead.

Usage: python3 harness/scripts/check_classic_script.py travelpi.js [...]
"""

import sys
from pathlib import Path

MARKERS = (
    ("__esModule", "CommonJS boilerplate (`__esModule`)"),
    ("export ", "an ESM `export` statement"),
    ("import ", "an ESM `import` statement"),
)


def offending_marker(line: str) -> tuple[str, str] | None:
    for marker, description in MARKERS:
        if marker == "__esModule":
            if marker in line:
                return marker, description
        elif line.startswith(marker):
            # Column 0 only: the compiler emits these at the top level, and matching
            # indented text would flag the word inside a string or template literal.
            return marker, description
    return None


def check(name: str) -> bool:
    path = Path(name)
    if not path.is_file():
        print(f"error: {name}: no such file", file=sys.stderr)
        return False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        found = offending_marker(line)
        if found:
            print(
                f"error: {name}:{number}: compiled as a module ({found[1]}); "
                "it must remain a classic browser script",
                file=sys.stderr,
            )
            return False
    return True


def main(paths: list[str]) -> int:
    if not paths:
        print("usage: check_classic_script.py <artifact.js> [...]", file=sys.stderr)
        return 2
    results = [check(name) for name in paths]
    if not all(results):
        return 1
    print(f"classic-script guard passed: {', '.join(paths)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
