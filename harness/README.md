# Agent harness

This tree is the agent's harness: the prompts, memory, skills, tools and
orchestration around a frozen model. It follows the eight-component
decomposition in *Harness2: Recursive Agent Harnessing for an Open World*
(arXiv:2610.14224, Table 5), so a harness edit is a file diff.

| Code | Component | Path | Activation |
| --- | --- | --- | --- |
| C1 | System prompt | `harness/systemprompt.md` | every call |
| C2 | Guardrails | `harness/guardrails.md` | every call |
| C3 | Memory | `harness/LongTermMEMORY.md` | every call |
| C4 | Tool guidance | `harness/tool_descriptions/tool_guidance.md` | every call |
| C5 | Subagents | `harness/sub_agents/<name>/AGENT.md` | task tool |
| C6 | Skills | `harness/skills/<name>/SKILL.md` | skill tool |
| C7 | Scripts | `harness/scripts/<name>.py` | run via bash |
| C8 | Plugin | `harness/plugin/<name>.ts` | inside the tool loop |

`harness/library/` is the harness improvement library: one directory per adopted
harness, each holding the snapshot and an `EXPERIENCE.md`.

## Commands

```sh
python3 tools/harness2.py status       # what exists, what is mounted
python3 tools/harness2.py mount        # sync into .opencode/ and AGENTS.md
python3 tools/harness2.py validate     # the gate; run before every commit
python3 tools/harness2.py library add --domain <d> --task <t> --experience <file>
```

## Current state

All four always-on components are filled, two skills and one subagent and one script
exist, and the plugin lever is empty on purpose: a plugin is only justified by
repeated evidence that prose cannot stop a mechanical failure, and no such evidence
exists here yet.

## Rules that bind an edit

1. Always-on text is the expensive option: every word is in context on every
   run and competes with the agent's output budget. Prefer, in this order:
   a skill (recognisable trigger), a script (deterministic operation), a
   subagent (large input, small answer), a plugin (enforced in the tool loop),
   and only then a short always-on rule — cutting something else to pay for it.
2. A skill exists only when the always-on text carries the trigger sentence, with the
   directory name verbatim: "When <situation>, load the `<name>` skill." The gate
   looks for that sentence, not for a passing mention — the trigger line ships in the
   same edit.
3. A script named from a skill or from always-on text must ship in the same
   edit: skill helpers at `harness/skills/<name>/scripts/<file>.py`, shared
   helpers at `harness/scripts/<file>.py`.
4. No `{{` or `{%` in always-on text. OpenCode reads these files verbatim, so a
   brace placeholder would reach the agent as literal text; runtimes that do render
   always-on text fail on it outright. Either way it is a defect.
5. A harness changes HOW the agent works, never WHAT SHAPE it delivers. Where a
   task names fields, columns, or an order, that shape belongs to the request.
6. Edit `harness/`, then run `mount`. Never hand-edit `.opencode/` copies or the
   managed `AGENTS.md` block; `validate` treats divergence as a defect.
