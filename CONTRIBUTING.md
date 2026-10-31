# Contributing

Thanks for helping. Bug reports, fixes and documentation are welcome. For vulnerabilities, do not open a public issue; see [SECURITY.md](SECURITY.md).

## Dev setup

You need Node.js (>= 16.20), npm, Python 3, `make` and git. You do not need a Pi to build or test.

```sh
npm ci
make test
```

- `make test` is the product gate: it builds the browser scripts, typechecks, compiles the helper and runs every test. Run it before sending a change.
- `make check` is the full gate: `make harness-check` (syncs and validates the agent harness under `harness/` and `AGENTS.md`) and then `make test`. Maintainers use it; contributors are not blocked by the agent tooling.

Run one test on its own, for example `python3 tests/readiness.py` or `node tests/frontend-runtime.js`. Do not run the build scripts alone (`npm run build:app` and `build:runtime` write to `dist/` and copy the browser artifacts); go through `make test` so artifacts and tests stay in step.

The helper `helper/travelpi-cockpit` has no `.py` extension. The Python tests load it with `importlib.machinery.SourceFileLoader` and stub the host commands, so they run on a laptop. Read the matching test before changing behavior: the tests are the executable contract for the projection, the contracts and the helper protocol.

## Where changes go

- Presentation and DOM events: `travelpi.ts`.
- Status projection: `travelpi-projection.ts`.
- Mutation and status contracts: `travelpi-contracts.ts` (and only there).
- Host behavior: `helper/travelpi-cockpit`.
- Packaging and units: `systemd/` and the `Makefile`.

`travelpi.js` and `travelpi-typed.js` are generated and committed. Rebuild them with `make test`; never edit them by hand. They must remain classic browser scripts (no `export`, no `__esModule`); `make test` guards this.

## Principles and guardrails

- **Staged, then confirmed, then applied.** Every mutation is shown, confirmed in the browser and enforced again in the helper. Never report an action as applied when it was refused, staged or rejected, and a failed identity change must restore the previous one.
- **Honest unavailable.** Do not claim a host capability the host has not demonstrated; surface an unavailable notice instead of staging a command that cannot run.
- Never persist hotel credentials, passwords or hotel MAC identities. Never automate captive-portal login.
- No new dependency, framework, bundler, external font or remote asset. The existing `npm`/`tsc` build is the only one.
- Define a mutation or status contract once, in `travelpi-contracts.ts`.
- Do not widen the helper into a general shell: its arguments are allowlisted.
- Keep it light: the target is a 512 MB Pi.

## Test-only overrides: `TRAVELPI_TEST=1`

The root-run scripts under `systemd/` accept environment overrides for the commands and paths they use (`TRAVELPI_IP`, `TRAVELPI_SYSTEMCTL`, `TRAVELPI_NMCLI`, `TRAVELPI_STATE_DIR`, `TRAVELPI_SYS_ROOT`, `ADGUARD_YAML` and similar) so tests can run them against a sandbox with shimmed tools. These are honored only when `TRAVELPI_TEST=1` is set; otherwise each script unsets them and uses the production paths, so a hostile environment cannot choose a command or file a root script uses. Any new override that selects a command to execute or a file to write must be added to that gate, and any test that relies on one must set `TRAVELPI_TEST=1`. Documented user-facing settings (`TRAVELPI_WAN_IFACE`, `TRAVELPI_AUTOTUNE_WAN`, `TRAVELPI_ULA_PREFIX_FILE`, `HOTEL_PROFILE`) work without it.

## Deploying touches a real host

`make deploy` installs units, sysctl, modprobe and NetworkManager files, restarts services and may interrupt the Pi's own network. Read the README section "What make deploy changes on the host" and the `deploy` target first. You do not need to deploy to contribute, and please do not claim hardware behavior you have not observed.

## Issue tracking in this repo

`.scratch/` and `docs/agents/` are the maintainers' local issue tracker (markdown files) and its conventions, used by coding agents; `CONTEXT.md` holds domain vocabulary and `docs/adr/` the decisions. As a contributor you can simply use GitHub issues and pull requests.
