---
name: travelpi-change
description: Change TravelPi Cockpit behavior, contracts, projection or presentation, and verify the change with this repository's build, guard and test suite.
---

# TravelPi change

Use this for any change that alters what the cockpit shows or does.

## 1. Find the layer

| Intent | File |
| --- | --- |
| Presentation, DOM, events, polling | `travelpi.ts` |
| Status derivation, view model | `travelpi-projection.ts` |
| Mutation and status shapes | `travelpi-contracts.ts` |
| Host behavior, allowlisted commands | `helper/travelpi-cockpit` |
| Packaging, units, install paths | `systemd/`, `Makefile`, `manifest.json` |

Checks that change with it:

| Layer | Test |
| --- | --- |
| Projection | `tests/status-view-model.js`, `tests/typed-status-view-model.js` |
| DOM/event shell | `tests/frontend-runtime.js` |
| Mutation coordinator | `tests/mutation-coordinator.js` |
| Contracts (types) | `tests/typescript-contracts.ts` via `npm run typecheck` |
| Helper commands | `tests/helper-*.py`, `tests/helper-contract.sh`, `tests/readiness.py`, `tests/radio-capabilities.py`, `tests/power-telemetry.py`, `tests/sqm-persistence.py`, `tests/vpn-status.py` |

## 2. Confirm the language

Read `CONTEXT.md` for the domain term you are touching and check that your change
keeps the documented safety boundary. If the change introduces a term or a durable
decision, update `CONTEXT.md` or add `docs/adr/NNNN-<slug>.md` in the same change.

## 3. Change the lowest layer that owns the behavior

- Add a shape to `travelpi-contracts.ts`; never restate it in the browser layer.
- Derive display values in `travelpi-projection.ts`; keep `travelpi.ts` DOM-only.
- Add a host command to the helper's allowlist; never a shell escape hatch.
- Edit generated artifacts by rebuilding, never by hand.

## 4. Extend the contract test

Add the failing case to the matching test first, then make it pass. Tests are plain
scripts with asserts; follow the neighbouring file's style rather than introducing a
framework.

## 5. Verify

```sh
make check
```

It must pass end to end: both builds, typecheck, the classic-script guard, helper
compilation, and every test. If a step fails, fix the cause; do not remove the check
or narrow the test.

## 6. Reopen what you produced

- Diff the generated artifacts as well as the sources.
- Confirm user-visible values still arrive as values, not placeholders or
  "see the logs".
- Report which checks actually ran.

## Failure modes to avoid

- Editing `travelpi.js` or `travelpi-typed.js` directly: the next build overwrites it.
- Claiming finish after `npm run build:app` only: the runtime artifact and tests are stale.
- Adding a framework, bundler or remote asset to a 512 MB target.
- Surfacing a capability the helper cannot execute instead of an honest unavailable notice.
