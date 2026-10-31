# C2 Guardrails (Every call)

These hold on every task, regardless of tool or request.

- Never persist hotel credentials, passwords or hotel MAC identities. Remembered
  SSIDs are the only permitted convenience hint, and existing NetworkManager
  profiles stay authoritative.
- Never report an action as applied when the mutation coordinator refused, staged
  or rejected it. A failed identity change must attempt to restore the previous
  working identity.
- Never automate captive-portal login. Never claim a host capability the host has
  not demonstrated: when the evidence is missing, surface the honest unavailable
  notice instead of staging a command the coordinator cannot execute.
- Never add a new build step, dependency, framework, external font or remote asset:
  the existing `npm`/`tsc` build through `make check` is the only one. `travelpi.js`
  and `travelpi-typed.js` must stay classic browser scripts: no `export`, no
  `__esModule` boilerplate.
- Never duplicate a mutation or status contract outside `travelpi-contracts.ts`.
- Never make the Cockpit package directory writable by the Cockpit web user.
- Do not run `make deploy` or reach a live Pi unless the person asks for it.
- Do not widen the helper into a general shell; its arguments are allowlisted and
  its surface is intentionally narrow.
