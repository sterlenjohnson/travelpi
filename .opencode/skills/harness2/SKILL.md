---
name: harness2
description: Install and reproduce the Harness2 recursive agent harnessing setup in a repository — the eight-component editable harness tree, the mount/validate tooling, and the harness improvement library — then run the contrastive Propose–Probe–Compose improvement loop.
compatibility: opencode
metadata:
  source: arXiv:2610.14224
  upstream: https://github.com/google-research/harness2
---

# Harness2 setup

Reproduces the harness from *Harness2: Recursive Agent Harnessing for an Open World*
(arXiv:2610.14224): an execution harness made of eight editable file-level
components, a harness improvement library, and a validation gate. Use this when a
repository should have an explicit, editable agent harness, or when you want the
improvement loop rather than one-off prompt edits.

## What gets installed

```text
harness/
  systemprompt.md              C1  always on
  guardrails.md                C2  always on
  LongTermMEMORY.md            C3  always on
  tool_descriptions/
    tool_guidance.md           C4  always on
  skills/<name>/SKILL.md       C6  on demand (skill tool), helpers in scripts/
  sub_agents/<name>/AGENT.md   C5  on demand (task tool), own context
  scripts/<name>.py            C7  run via bash
  plugin/<name>.ts             C8  always registered, acts in the tool loop
  library/index.md             improvement library: adopted harnesses + EXPERIENCE.md
  .mount-state.json            generated
tools/harness2.py              scaffold | mount | validate | status | library
```

Always-on text is mounted into `AGENTS.md` between `harness2:begin`/`harness2:end`
markers. On-demand components are copied into the runtime
(`.opencode/skills/`, `.opencode/agents/`, `.opencode/plugins/` for OpenCode).
`harness/` is the source of truth; never hand-edit the copies.

## Procedure

Run from the target repository root.

### 1. Preflight

- Confirm the runtime and its component paths. This tool mounts the OpenCode layout:
  `.opencode/skills/`, `.opencode/agents/`, `.opencode/plugins/`, with always-on text
  in `AGENTS.md`. For another runtime, keep the `harness/` tree — it is runtime
  neutral — and mount the on-demand components by hand to that runtime's paths.
- Identify the repository's own check command (`make check`, `npm test`, …). The
  harness gate joins it; it does not replace it.
- Read the domain doc (`CONTEXT.md`, `README.md`, ADRs) — the always-on files must
  state facts, and the facts come from there.

### 2. Install the tool

```sh
mkdir -p tools
cp .opencode/skills/harness2/scripts/harness2.py tools/harness2.py
python3 tools/harness2.py --help
```

In a repository that does not have this skill installed, copy
`scripts/harness2.py` from wherever the skill lives.

### 3. Scaffold

```sh
python3 tools/harness2.py scaffold
```

This creates the tree, the library index, a README in each lever directory, and an
empty managed block in `AGENTS.md`. Stub always-on files carry a `harness2:stub`
marker and are **skipped at mount**, so placeholder text never reaches an agent.

### 4. Fill the always-on components from evidence

Replace each stub and delete its marker. Rules:

- Write facts, not rediscovery procedures: "in this repo, role X maps to file B"
  beats "find the mapping". Anchor guessed facts as unverified or omit them.
- Keep the whole always-on surface under ~1500 words. Every word is paid for on
  every run and competes with the agent's output budget. If you add, cut.
- No `{{` or `{%`: OpenCode reads always-on text verbatim, so a brace placeholder
  reaches the agent as literal text, and a runtime that renders the text fails on it.
- Guardrails are hard constraints that hold regardless of task; memory is durable
  domain facts; tool guidance is when and how to use existing tools.

### 5. Seed on-demand components, cheapest form first

Add a component only when a real deficiency names it. Order of preference:

| Form | Use when | Cost |
| --- | --- | --- |
| Skill `C6` | a recognisable trigger: a procedure for a document type, format, or recurring situation | nothing until invoked |
| Script `C7` | a deterministic operation done by hand and done wrong or slowly | nothing until run |
| Subagent `C5` | a bounded investigation whose input is large and whose answer is small | one extra context |
| Plugin `C8` | a repeated mechanical failure that prose demonstrably cannot stop | nothing in context, acts in the loop |
| Always-on prose `C1`–`C4` | a short rule that genuinely applies to every run | paid every run |

A skill exists only once the always-on text says `When <situation>, load the
\`<name>\` skill.`, with the directory name verbatim: a passing mention is not a
trigger line, and the gate rejects it. Write the trigger sentence in the same edit. Any script a skill names must ship with it, at
`harness/skills/<name>/scripts/<file>.py` or `harness/scripts/<file>.py`.

Leave a lever empty rather than inventing a component. An empty directory with its
README is the correct starting state, and "no plugin" is the right answer until
prose has been shown to fail.

### 6. Mount and gate

```sh
python3 tools/harness2.py mount
python3 tools/harness2.py validate
```

Then join the gate to the repository's check command so it cannot be skipped:

```make
check:
	python3 tools/harness2.py validate
	# ... existing build, typecheck and test steps ...
```

Commit the mounted copies. `validate` fails on drift, so a stale copy is caught by
the check rather than by a silently different agent.

### 7. Point the repository at it

Add to `AGENTS.md`, outside the managed block:

```markdown
## Agent harness

The editable harness is `harness/` (see `harness/README.md`). Edit it, then run
`python3 tools/harness2.py mount`. The gate runs in `make check`.
```

## The improvement loop

For a task the base harness handles badly, run one contrastive step. Each session
gets its evidence as files, never as a pasted prompt, and never sees a rubric,
score, or grader verdict.

1. **Propose (reference)** — run the task under the current harness. That rollout is
   the reference, not a verdict: it shows how the harness behaves.
2. **Propose (candidates)** — with the reference in hand, draft two candidates as
   harness edits: an *invariant* one for how the agent works (planning, tool use,
   context, delegation) and a *domain* one for what a practitioner of this task
   knows. Keep the scopes separate; each candidate commits to its own dimension.
3. **Probe** — execute both candidates on the same task under matched settings.
   Compare trajectories against the reference. The contrast shows whether the edit
   changed the targeted behavior; it does not prove correctness.
4. **Compose** — produce one successor: merge the supported edits, revise
   conflicts, adopt one candidate, or keep the base. Tie every decision to a
   specific moment in a trajectory. Execute the composed harness and record the
   decisions.
5. **Select** (only for k > 1) — compare anonymized deliverables against the
   request. The selector returns an existing deliverable and never writes new
   content.

Budget `k`: *parallel* recursion probes `k` invariant and `k` domain candidates and
runs `k` independent compositions over the full pool; *sequential* recursion chains
`k` steps, each conditioned on the previous harness and accumulated evidence.
`k=1` reduces to the single contrastive step and skips selection.

After the task, **reflect**: retain the adopted harness and only the lessons
supported by execution contrasts.

```sh
python3 tools/harness2.py library add --domain <domain> --task <task> \
  --experience <path/to/EXPERIENCE.md>
```

`EXPERIENCE.md` states the situation, the recurring weakness, which edits earned
their place, the evidence, and when the entry should not be reused. An entry is a
hypothesis for the next task, never an inherited harness: the next task starts from
the base harness and reuses components selectively.

## Definition of done

- `python3 tools/harness2.py validate` passes, and runs inside the repository's
  check target.
- Every always-on file states repository facts, carries no stub marker, and no
  skill is orphaned from its trigger line.
- Each on-demand component answers a deficiency you can point at; empty levers stay
  empty.
- `AGENTS.md` points at `harness/` in its own prose while the generated block carries
  the always-on text; nothing else in `AGENTS.md` restates a component.
- Nothing in the harness changes the shape of a deliverable the task specified.

## Do not

- Paste the whole paper or its prompts into always-on text.
- Copy a component from another repository's library without re-verifying its
  workspace facts.
- Let a session see a grader verdict, rubric or score while it edits the harness.
- Add a component "for completeness" that no trajectory asked for.
- Edit `.opencode/` copies or the managed `AGENTS.md` block by hand.
