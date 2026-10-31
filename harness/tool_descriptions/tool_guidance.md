# C4 Tool guidance (Every call)

- `make check` is the contract: it builds both artifacts, typechecks the contracts,
  guards the classic-script artifact, compiles the helper, and runs every test.
  Never claim a change is done on a partial run.
- Run builds through `make check`. `npm run build:app` and `npm run build:runtime`
  write into `dist/` and copy the browser artifacts; running them alone leaves the
  committed artifacts and the tests out of step.
- Read the matching test under `tests/` before editing behavior; the tests are the
  executable contract for the projection, the contracts and the helper protocol.
- `helper/travelpi-cockpit` has no `.py` extension: compile it with
  `python3 -m py_compile helper/travelpi-cockpit`, and exercise it through
  `tests/` rather than by hand, because it expects a Pi host.
- `harness/scripts/check_classic_script.py` is the module-emit guard; run it on any
  browser artifact that is generated or edited.
- `make deploy` and `scp` reach a live Pi. Read them; run them only when asked.
