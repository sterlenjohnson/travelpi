# Harness2 reference

Distilled from *Harness2: Recursive Agent Harnessing for an Open World*
([arXiv:2610.14224v1](https://arxiv.org/html/2610.14224v1), Google Cloud AI
Research / Northwestern, 2026-10-09). Code: `google-research/harness2`.
`tools/harness2.py` is an independent implementation of the setup, not the
authors' code.

## The eight components (paper Table 5)

| Group | Component | File | Activation | Definition |
| --- | --- | --- | --- | --- |
| Context construction | C1 System prompt | `systemprompt.md` | every call | persona and top-level procedure followed on all tasks |
| Context construction | C2 Guardrails | `guardrails.md` | every call | hard constraints that hold regardless of task or tool |
| Context construction | C3 Memory | `LongTermMEMORY.md` | every call | durable domain facts persisted across tasks in a domain |
| Context construction | C6 Skills | `skills/<name>/SKILL.md`, `skills/<name>/scripts/*` | skill tool | specialist procedure loaded only when invoked |
| Tool interface | C4 Tool guidance | `tool_descriptions/tool_guidance.md` | every call | when and how each existing tool should be used |
| Tool interface | C7 Scripts | `scripts/<name>.py` | run via bash | a deterministic capability executed instead of reasoned through |
| Orchestration | C5 Subagents | `sub_agents/<name>/AGENT.md` | task tool | delegated worker in its own context returning only its result; the only component that adds an inference context |
| Middleware control | C8 Plugin | `plugin/<name>.ts` | inside the tool loop | a hook that enforces a behavior rather than instructing it |

The decomposition extends AHE (Lin et al., 2026) by one component: the plugin.

## Three rules that discard a whole proposal

Validation runs before any rollout; a harness failing it is thrown away entire.

1. **Every skill needs a trigger line.** The directory name must appear verbatim in
   `systemprompt.md` or `guardrails.md`, in the same edit:
   "When \<the situation\>, load the '\<name\>' skill." An unnamed skill is never opened.
2. **No template braces in always-on text.** In the paper's runner those files are
   rendered with Jinja `StrictUndefined`, so a doubled `{{` placeholder or a `{%` tag
   kills the job before any work starts. In a runtime that reads the files verbatim
   the brace reaches the agent as literal text. Either way, refuse it.
3. **Every script you name must exist**, shipped in the same proposal: a skill's own
   helper at `skills/<name>/scripts/<file>.py`, shared helpers at `scripts/<file>.py`.

Two further constraints from the same prompt set:

- The deliverable's shape belongs to the request, never to the harness. Where the
  task names fields, columns, sheets, sections or an order, a component that adds
  explanatory columns, renames a header, or surfaces intermediate values is changing
  what was asked for.
- A value the task asks for must be delivered as a value. A formula, a placeholder,
  or a described-but-unperformed calculation leaves the reader to finish the work.

## How to weigh evidence (editor prompts)

- A failure that repeats across the base rollouts is a real property of the base
  harness and the strongest thing to act on. A defect in 1/k is noise.
- Each candidate has one rollout, so one outcome is weak evidence either way. An
  edit earns its place when a specific moment in a trajectory shows the mechanism.
- Judge the downside as heavily as the upside. The costliest failure is a run that
  produces nothing.
- If any rollout associated with an edit produced nothing, treat that edit as unsafe.
- Prefer, in order: a divergence between runs, a repeated concrete failure, a risk
  visible but not yet realised. Never fix what the runs already got right.

## The two scopes

- **INV** (invariant): how the agent works — planning, tool use, context management,
  retries, reading order, output paths, budgeting, scripts, hooks.
- **DOM** (domain): what a practitioner knows — deliverable, audience, decision,
  controlling sources, required structure, consistency relationships, expert
  omissions. Analytic move, artifact contract, decision rule, encoding.

Candidates are drawn independently from the same evidence and must not hedge toward
an average; a later stage compares and merges.

## Recursion budget

- Parallel: `k` reference executions, `k` INV and `k` DOM candidates, one rollout
  each, then `k` independent compositions each receiving the full pool.
- Sequential: `k` chained steps, each conditioned on the previous harness and the
  accumulated execution and improvement history.
- Final selection for `k > 1`: an agentic selector compares anonymized deliverables
  against the request and returns one, without seeing which harness produced it.

## Improvement library

`R(t+1) = Update(R(t), H*(t), D(t))` — each entry is the full adopted harness tree
plus an `EXPERIENCE.md` recording the applicable situation, the lessons, and the
supporting evidence. An index lists entries. Executable components are retained, not
summarized as prose. Nothing is added when the evidence is insufficient.

Entries are read-only context for the next refinement, not inherited harnesses: the
next task starts from the base harness and reuses components selectively, re-verifying
any recorded workspace fact.

## Reported effects

Single contrastive step over base harness, four executor–harness configurations
(Gemini 3.5 Flash / GLM-5 under OpenCode / Codex): up to +11.5 on WorkBuddy-Bench,
+4.5 on JobBench, +11.8 pp on LAB Partial. Parallel recursion at k=5 adds a further
2.9–3.9, 3.0–4.2, and 2.6–6.7 points respectively. Ablations: removing the library
costs 3.1 / 1.8 points, removing the INV–DOM scoping 2.9 / 3.7, removing composition
1.6 / 1.9. A library built at k=5 transfers across benchmarks. The same model can
serve as executor and editor without losing the gain.

## Costs and limits

- Always-on text is the expensive form; a run that reasons until the budget is gone
  and delivers nothing is the dominant failure mode, and extra prose makes it likelier.
- Harness refinement fixes procedural failures well and knowledge gaps only when the
  evidence is in the task material; it is not a substitute for missing domain data.
- Parallel proposal and composition sessions can run concurrently, but realized
  latency depends on available concurrency and rollout duration.
- Rollouts in the paper were capped at 200 model turns and 3,600 seconds with no
  memory of other tasks.
