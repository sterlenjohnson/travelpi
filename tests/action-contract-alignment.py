#!/usr/bin/env python3
"""Guard: one mutation contract, three layers, no copy drift.

travelpi-contracts.ts owns the action names and payload shapes.
helper/travelpi-cockpit owns the host allowlist (its own seam, host-side).
travelpi-mutations.js owns the coordinator semantics and every user-visible
confirmation string. travelpi.ts builds payloads from the form controls and
types no confirmation copy.

The guard asserts the three action sets are identical, the availability
exclusion matches the contract, every descriptor carries its full copy, and the
presentation layer contains no confirmation strings.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = (ROOT / "travelpi-contracts.ts").read_text()
HELP = (ROOT / "helper" / "travelpi-cockpit").read_text()
MUTATIONS = (ROOT / "travelpi-mutations.js").read_text()
TS = (ROOT / "travelpi.ts").read_text()

failures = []


def check(cond, label):
    if not cond:
        failures.append(label)


def contract_actions():
    block = re.search(r"export const mutationActions = \[(.*?)\] as const;", CONTRACTS, re.S)
    if not block:
        return None
    return [m.group(1) for m in re.finditer(r'"([a-z0-9_]+)"', block.group(1))]


def contract_unavailable():
    block = re.search(r"Exclude<MutationAction,\s*((?:\"[a-z0-9_]+\"(?:\s*\|\s*)?)+)>", CONTRACTS)
    if not block:
        return None
    return [m.group(1) for m in re.finditer(r'"([a-z0-9_]+)"', block.group(1))]


def helper_actions():
    block = re.search(r"^ACTION_FIELDS\s*=\s*\{(.*?)^\}", HELP, re.S | re.M)
    if not block:
        return None
    return [m.group(1) for m in re.finditer(r"^\s+'([a-z0-9_]+)':", block.group(1), re.M)]


def descriptor_blocks():
    start = MUTATIONS.find("var descriptors = {")
    if start < 0:
        return None
    block = MUTATIONS[start:]
    names = [m.group(1) for m in re.finditer(r"^\s{8}([a-z0-9_]+):\s*\{", block, re.M)]
    bodies = {}
    for name in names:
        at = re.search(r"^\s{8}" + name + r":\s*\{", block, re.M)
        depth = 0
        i = block.index("{", at.end() - 1)
        j = i
        while j < len(block):
            if block[j] == "{":
                depth += 1
            elif block[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        bodies[name] = block[i:j + 1]
    return names, bodies


def main():
    names = contract_actions()
    check(names is not None and len(names) > 10, "contract action list must parse")
    unavailable = contract_unavailable()
    check(unavailable is not None, "contract availability exclusion must parse")

    helper = helper_actions()
    check(helper is not None and len(helper) > 10, "helper ACTION_FIELDS must parse")

    parsed = descriptor_blocks()
    check(parsed is not None, "mutations descriptor table must parse")

    if failures:
        return

    contract_set, helper_set, descriptor_set = set(names), set(helper), set(parsed[0])
    check(helper_set == contract_set,
          f"helper allowlist differs from the contract: extra={sorted(helper_set - contract_set)} "
          f"missing={sorted(contract_set - helper_set)}")
    check(descriptor_set == contract_set,
          f"coordinator descriptors differ from the contract: extra={sorted(descriptor_set - contract_set)} "
          f"missing={sorted(contract_set - descriptor_set)}")

    bodies = parsed[1]
    unavailable_desc = {n for n, b in bodies.items() if re.search(r"available:\s*false", b)}
    check(unavailable_desc == set(unavailable),
          f"unavailable actions differ from the contract's Exclude list: "
          f"descriptors={sorted(unavailable_desc)} contract={sorted(unavailable)}")

    for name in parsed[0]:
        body = bodies[name]
        for field in ("title", "message", "success"):
            check(re.search(r"\b" + field + r":", body) is not None,
                  f"descriptor {name} has no {field} copy")
        for field in ("staged", "refresh"):
            check(re.search(r"\b" + field + r":\s*(true|false)", body) is not None,
                  f"descriptor {name} has no boolean {field}")

    # Presentation must not type confirmation copy: every requestConfirmation
    # call is (action, payload) with at most those two arguments, payload
    # literals are contract values, and success strings live only in the
    # coordinator.
    calls = re.findall(r'requestConfirmation\(((?:[^{}]|\{[^{}]*\})*)\);', TS)
    check(len(calls) >= 10, f"expected the confirmation call sites to parse, got {len(calls)}")
    for call in calls:
        parts, depth, current = [], 0, ""
        for ch in call:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(current)
                current = ""
            else:
                current += ch
        parts.append(current)
        check(len(parts) <= 2, f"requestConfirmation takes more than (action, payload): {call[:70]!r}")
        first = re.match(r'\s*"([a-z0-9_]+)"', parts[0])
        generic = re.match(r'\s*action\s+as\s+MutationAction\s*$', parts[0]) is not None
        if generic:
            # The generic [data-action] button path: the action is validated
            # against ACTION_COMMANDS, which is built from the descriptors.
            check("ACTION_COMMANDS[action]" in TS,
                  "the generic data-action path must validate against ACTION_COMMANDS")
        else:
            check(first is not None, f"requestConfirmation has no literal action: {parts[0][:60]!r}")
        if first:
            check(first.group(1) in contract_set,
                  f"requestConfirmation uses an action outside the contract: {first.group(1)}")
            check(len(parts) == 2, f"requestConfirmation needs its payload: {call[:70]!r}")

    copy_in_coordinator = len(re.findall(r'request completed\."', MUTATIONS))
    copy_in_presentation = len(re.findall(r'request completed\."', TS))
    check(copy_in_coordinator >= 10, f"coordinator should own the success copy, found {copy_in_coordinator}")
    check(copy_in_presentation == 0, f"travelpi.ts types success copy {copy_in_presentation} time(s)")

    if failures:
        print("action contract alignment guard FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print(f"action contract alignment guard checks passed ({len(names)} actions)")


if __name__ == "__main__":
    main()
