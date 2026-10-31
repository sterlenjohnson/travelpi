---
name: pi-host-evidence
description: Ground a TravelPi change in verified host facts, and surface an honest unavailable notice when the evidence for a capability, path, unit or threshold is missing.
---

# Pi host evidence

Use this whenever a change asserts something about the Pi: that a capability exists,
that a unit or path is present, that a radio supports a band, or that a threshold is
safe.

## 1. State the claim as a question

Write down the single fact the change depends on, for example: "is a LAN uplink
present so a radio role swap is safe?" or "does this NIC report 6 GHz support?".

## 2. Look for evidence in this repository, in this order

1. `helper/travelpi-cockpit` — constants, allowlisted commands, probe timeouts.
2. `systemd/` and `Makefile` — units, install paths, owners, modes.
3. `tests/` — the behaviour the repository already guarantees.
4. `CONTEXT.md`, `README.md`, `docs/adr/` — documented vocabulary and decisions.

Existing code is evidence of intent, not proof that the host behaves that way. When
the claim is about live hardware, say which probe produced the answer.

## 3. Decide, do not guess

- Evidence supports it: implement, and anchor the fact in the comment or memory as a
  workspace fact ("on this host, ...") in the untracked `harness/LongTermMEMORY.local.md`, not in tracked files.
- Evidence is missing: surface the honest unavailable notice with the reason. Do not
  stage a command the coordinator cannot execute, and do not invent a path, unit,
  sensor or standard.
- Evidence is partial: degrade explicitly (show what is known, mark the rest
  unverified) rather than filling the gap.

## 4. Keep the boundary intact

- Readiness facts stay read-only; a disruptive action needs confirmation.
- A failed identity change attempts to restore the previous working identity.
- Captive portals are detected, never auto-authenticated.
- Credentials and hotel MAC identities are not persisted; remembered SSIDs are
  non-secret hints only.

## 5. Record and verify

If the fact is durable across tasks, add it to `harness/LongTermMEMORY.md` labelled
as a workspace fact; if it is task-specific, keep it in the change instead. Then run
`make check` and report which checks ran.

## Failure modes to avoid

- Reporting `available: true` because the code path exists, when no probe confirmed it.
- Treating a role swap as safe without a verified LAN uplink.
- Turning a missing measurement into a zero, a dash, or a plausible-looking default.
- Adding a "temporary" capability flag instead of surfacing the unavailable notice.
