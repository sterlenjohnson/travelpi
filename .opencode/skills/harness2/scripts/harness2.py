#!/usr/bin/env python3
"""Harness2 harness tooling.

Scaffold, mount, validate and extend the eight-component agent harness from
"Harness2: Recursive Agent Harnessing for an Open World" (arXiv:2610.14224),
together with its harness improvement library.

Commands:
    scaffold  create the harness tree, the improvement library, and mount it
    mount     sync harness components into the OpenCode runtime and AGENTS.md
    validate  run the harness gate; exits 1 on any defect that discards a harness
    status    show each component, its activation, and whether it is mounted
    library   add an adopted harness plus EXPERIENCE.md to the improvement library

The harness tree is the editable surface. Files you write in harness/ are the
source of truth; `.opencode/` and the managed AGENTS.md block are generated.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

BEGIN = "<!-- harness2:begin -->"
END = "<!-- harness2:end -->"
STUB = "<!-- harness2:stub -->"
STATE = ".mount-state.json"
LIBRARY = "library"
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SCRIPT_REF_RE = re.compile(r"scripts/([A-Za-z0-9_.\-]+\.(?:py|sh|mjs|js|ts))")
MAX_ALWAYS_ON_WORDS = 1500


def trigger_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"load the\s+`?{re.escape(name)}`?\s+skill", re.IGNORECASE)


class HarnessError(Exception):
    """A defect that stops a command before it can make things worse."""


@dataclass(frozen=True)
class Component:
    path: str
    code: str
    name: str
    activation: str
    definition: str


ALWAYS_ON = (
    Component("systemprompt.md", "C1", "System prompt", "Every call",
              "Persona and top-level procedure followed on all tasks."),
    Component("guardrails.md", "C2", "Guardrails", "Every call",
              "Hard constraints that hold regardless of task or tool."),
    Component("LongTermMEMORY.md", "C3", "Memory", "Every call",
              "Durable domain facts persisted across tasks in a domain."),
    Component("tool_descriptions/tool_guidance.md", "C4", "Tool guidance", "Every call",
              "When and how each existing tool should be used."),
)

MOUNTED = (
    Component("skills", "C6", "Skills", "skill tool",
              "Specialist procedure loaded into context only when invoked, "
              "so it costs nothing on tasks that do not need it."),
    Component("sub_agents", "C5", "Subagents", "task tool",
              "Delegated worker running in its own context window and returning "
              "only its result: the sole component that adds an inference context."),
    Component("plugin", "C8", "Plugin", "Inside the tool loop",
              "Hook around tool calls and turn boundaries: it enforces a behavior "
              "rather than instructing it."),
)

SCRIPTS = Component("scripts", "C7", "Scripts", "Run via bash",
                    "A new deterministic capability, executed instead of being "
                    "reasoned through token by token.")

MOUNT_TARGETS = {
    "skills": ".opencode/skills",
    "sub_agents": ".opencode/agents",
    "plugin": ".opencode/plugins",
}


def harness_dir(root: Path) -> Path:
    return root / "harness"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def parse_frontmatter(text: str) -> tuple[dict[str, str], str, str]:
    """Return (frontmatter, body, problem) for a markdown component file."""
    if not text.startswith("---"):
        return {}, text, "missing frontmatter"
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text, "unterminated frontmatter"
    block = text[3:end].strip("\n")
    body = text[end + 4:]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.startswith((" ", "\t", "#")):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key in fields:
            return {}, body, f"duplicate frontmatter key '{key}'"
        fields[key] = value.strip().strip("'\"")
    return fields, body, ""


def stub(component: Component) -> str:
    return (
        f"{STUB}\n"
        f"# {component.code} {component.name} ({component.activation})\n"
        f"\n"
        f"{component.definition}\n"
        f"\n"
        f"Replace this file with facts established in this repository, then delete\n"
        f"the first line. While the stub marker is present the component is skipped\n"
        f"at mount time, so a scaffold never puts placeholder text in front of an\n"
        f"agent.\n"
    )


def lever_readme(component: Component) -> str:
    return (
        f"# {component.code} {component.name} — {component.activation}\n"
        f"\n"
        f"{component.definition}\n"
        f"\n"
        f"When this directory is empty, the lever is available and unused — the\n"
        f"Harness2 starting state. The directory names the lever so an editor can find\n"
        f"it, and nothing is paid for until a component exists here.\n"
    )


HARNESS_README = """# Agent harness

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

## Rules that bind an edit

1. Always-on text is the expensive option: every word is in context on every
   run and competes with the agent's output budget. Prefer, in this order:
   a skill (recognisable trigger), a script (deterministic operation), a
   subagent (large input, small answer), a plugin (enforced in the tool loop),
   and only then a short always-on rule — cutting something else to pay for it.
2. A skill exists only when its directory name appears verbatim in
   `systemprompt.md` or `guardrails.md`: "When <situation>, load the `<name>`
   skill." The trigger line ships in the same edit.
3. A script named from a skill or from always-on text must ship in the same
   edit: skill helpers at `harness/skills/<name>/scripts/<file>.py`, shared
   helpers at `harness/scripts/<file>.py`.
4. No `{{` or `{%` in always-on text. OpenCode reads these files verbatim, so a
   brace placeholder reaches the agent as literal text; a runtime that renders the
   text fails on it outright. Either way it is a defect.
5. A harness changes HOW the agent works, never WHAT SHAPE it delivers. Where a
   task names fields, columns, or an order, that shape belongs to the request.
6. Edit `harness/`, then run `mount`. Never hand-edit `.opencode/` copies or the
   managed `AGENTS.md` block; `validate` treats divergence as a defect.
"""

LIBRARY_INDEX = """# Harness improvement library

One directory per adopted harness: `library/<domain>/<task>/`.

Each entry holds:

- `harness/` — the full adopted tree, executable components included, not a
  summary of them;
- `EXPERIENCE.md` — the situation the harness was adopted for, the recurring
  weakness it addressed, which changes earned their place, the evidence behind
  them, and when the entry should not be reused.

Entries are read by later refinement sessions, so they are data, not
instructions: a mapping or threshold recorded here is a hypothesis for the next
task, re-verified against that task's evidence before reuse.

Nothing is added when the evidence does not support a reusable lesson. An empty
library is the correct starting state.

## Entries

"""


def ensure_stubs(root: Path, force: bool = False) -> tuple[list[str], list[str]]:
    created: list[str] = []
    skipped: list[str] = []

    def put(relative: str, text: str) -> None:
        path = root / relative
        if path.exists() and not force:
            skipped.append(relative)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        created.append(relative)

    for component in ALWAYS_ON:
        put(f"harness/{component.path}", stub(component))
    put("harness/README.md", HARNESS_README)
    put(f"harness/{LIBRARY}/index.md", LIBRARY_INDEX)
    for component in (*MOUNTED, SCRIPTS):
        put(f"harness/{component.path}/README.md", lever_readme(component))
    return created, skipped


def active_always_on(root: Path) -> list[tuple[Component, str]]:
    """Always-on components that carry real text (not stubs, not empty)."""
    active: list[tuple[Component, str]] = []
    for component in ALWAYS_ON:
        path = harness_dir(root) / component.path
        if not path.exists():
            continue
        text = read(path)
        if STUB in text or not text.strip():
            continue
        active.append((component, text))
    return active


def render_block(root: Path) -> str:
    lines = [
        BEGIN,
        "<!-- Generated by tools/harness2.py mount from harness/. "
        "Edit harness/, not this block. -->",
    ]
    for component, text in active_always_on(root):
        lines += [
            "",
            f"<!-- {component.code} {component.name} ({component.activation}): "
            f"harness/{component.path} -->",
            "",
            text.strip(),
        ]
    lines += ["", END]
    return "\n".join(lines)


def splice(agents_md: Path, block: str) -> str:
    text = read(agents_md) if agents_md.exists() else ""
    has_begin = BEGIN in text
    has_end = END in text
    if has_begin and has_end:
        head, rest = text.split(BEGIN, 1)
        _, tail = rest.split(END, 1)
        return head + block + tail
    if has_begin or has_end:
        raise HarnessError(
            f"{agents_md.name} has a broken harness2 block ({BEGIN if has_begin else END} is unpaired); "
            "remove the stray marker and run mount again"
        )
    prefix = text.rstrip("\n")
    separator = "\n\n" if prefix else ""
    return f"{prefix}{separator}{block}\n"


def mount_pairs(root: Path) -> list[tuple[Path, Path]]:
    """Every (source, destination) file pair the runtime needs."""
    pairs: list[tuple[Path, Path]] = []
    skills = harness_dir(root) / "skills"
    if skills.is_dir():
        for directory in sorted(p for p in skills.iterdir() if p.is_dir()):
            if not (directory / "SKILL.md").is_file():
                continue
            for source in sorted(directory.rglob("*")):
                if source.is_file():
                    pairs.append((source, root / MOUNT_TARGETS["skills"] / directory.name / source.relative_to(directory)))
    sub_agents = harness_dir(root) / "sub_agents"
    if sub_agents.is_dir():
        for directory in sorted(p for p in sub_agents.iterdir() if p.is_dir()):
            source = directory / "AGENT.md"
            if source.is_file():
                pairs.append((source, root / MOUNT_TARGETS["sub_agents"] / f"{directory.name}.md"))
    plugins = harness_dir(root) / "plugin"
    if plugins.is_dir():
        for pattern in ("*.ts", "*.js", "*.mjs"):
            for source in sorted(plugins.glob(pattern)):
                pairs.append((source, root / MOUNT_TARGETS["plugin"] / source.name))
    return pairs


def load_state(root: Path) -> dict:
    """Recorded mounts. Raises HarnessError rather than failing open."""
    path = harness_dir(root) / STATE
    if not path.exists():
        return {"runtime": "opencode", "mounted": []}
    try:
        state = json.loads(read(path))
    except json.JSONDecodeError as error:
        raise HarnessError(f"harness/{STATE} is corrupt ({error}); delete it and run mount again") from error
    if not isinstance(state, dict) or not isinstance(state.get("mounted", []), list):
        raise HarnessError(f"harness/{STATE} has an unexpected shape; delete it and run mount again")
    state.setdefault("mounted", [])
    return state


def owned_by_mount(root: Path, relative: str) -> bool:
    """True when a recorded mount path is one this tool is allowed to delete."""
    if not relative:
        return False
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    for target in MOUNT_TARGETS.values():
        prefix = f"{target}/"
        if relative.startswith(prefix) and len(candidate.parts) > len(Path(target).parts):
            return True
    return False


def save_state(root: Path, mounted: list[str]) -> None:
    path = harness_dir(root) / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"runtime": "opencode", "mounted": mounted}, indent=2) + "\n",
        encoding="utf-8",
    )


def mount(root: Path) -> list[str]:
    actions: list[str] = []

    agents_md = root / "AGENTS.md"
    block = render_block(root)
    previous = read(agents_md) if agents_md.exists() else ""
    updated = splice(agents_md, block)
    if updated != previous:
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        agents_md.write_text(updated, encoding="utf-8")
        actions.append("AGENTS.md: always-on block updated")
    else:
        actions.append("AGENTS.md: always-on block unchanged")

    pairs = mount_pairs(root)
    for source, destination in pairs:
        data = source.read_bytes()
        if destination.exists() and destination.read_bytes() == data:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        actions.append(f"{rel(root, destination)}: written")

    wanted = {rel(root, destination) for _, destination in pairs}
    state = load_state(root)
    pruned_parents: set[Path] = set()
    for stale in sorted(set(state["mounted"]) - wanted):
        if not owned_by_mount(root, stale):
            raise HarnessError(
                f"harness/{STATE} lists '{stale}', which is outside the mount targets "
                f"({', '.join(MOUNT_TARGETS.values())}); refusing to delete it"
            )
        path = root / stale
        if path.exists():
            path.unlink()
            actions.append(f"{stale}: removed")
        pruned_parents.add(path.parent)

    for directory in sorted(pruned_parents, key=lambda p: len(p.parts), reverse=True):
        if not directory.is_dir() or any(directory.iterdir()):
            continue
        if not owned_by_mount(root, f"{rel(root, directory)}/placeholder"):
            continue
        directory.rmdir()
        actions.append(f"{rel(root, directory)}: empty mount directory removed")

    if sorted(wanted) != sorted(state["mounted"]):
        save_state(root, sorted(wanted))
        actions.append(f"harness/{STATE}: updated")
    return actions


def validate(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    harness = harness_dir(root)

    if not harness.is_dir():
        return ["harness/ is missing; run: python3 tools/harness2.py scaffold"], warnings

    always_on_text_parts: list[str] = []
    always_on_words = 0
    for component in ALWAYS_ON:
        path = harness / component.path
        if not path.exists():
            errors.append(f"{component.code} {component.name}: harness/{component.path} is missing")
            continue
        text = read(path)
        always_on_text_parts.append(text)
        always_on_words += len(text.split())
        if STUB in text:
            warnings.append(f"{component.code}: harness/{component.path} is still a stub (skipped at mount)")
        if "{{" in text or "{%" in text:
            errors.append(
                f"{component.code}: harness/{component.path} contains a template brace '{{{{' or '{{%'; "
                "always-on text is not rendered here, but a harness that carries a brace placeholder "
                "either loses that text or breaks on a runtime that does render it"
            )

    if always_on_words > MAX_ALWAYS_ON_WORDS:
        warnings.append(
            f"always-on text is {always_on_words} words (soft budget {MAX_ALWAYS_ON_WORDS}); "
            "every word is paid for on every run"
        )

    always_on_text = "\n".join(always_on_text_parts)

    skills = harness / "skills"
    if skills.is_dir():
        for directory in sorted(p for p in skills.iterdir() if p.is_dir()):
            skill_md = directory / "SKILL.md"
            label = f"C6 skill {directory.name}"
            if not skill_md.is_file():
                errors.append(f"{label}: missing SKILL.md (a directory without one is invisible)")
                continue
            text = read(skill_md)
            fields, body, problem = parse_frontmatter(text)
            if problem:
                errors.append(f"{label}: {problem}")
                continue
            if not NAME_RE.fullmatch(directory.name):
                errors.append(f"{label}: name must match ^[a-z0-9]+(-[a-z0-9]+)*$")
            if fields.get("name") != directory.name:
                errors.append(f"{label}: frontmatter name must be '{directory.name}' (matches the directory)")
            if not fields.get("description"):
                errors.append(f"{label}: frontmatter description is required")
            if not trigger_pattern(directory.name).search(always_on_text):
                errors.append(
                    f"{label}: no trigger line — systemprompt.md or guardrails.md must say "
                    f"\"When <situation>, load the '{directory.name}' skill.\""
                )
            for reference in sorted(set(SCRIPT_REF_RE.findall(body))):
                candidates = (directory / "scripts" / reference, harness / "scripts" / reference)
                if not any(candidate.is_file() for candidate in candidates):
                    errors.append(
                        f"{label}: names scripts/{reference} but ships no such file "
                        f"(expected {rel(root, directory)}/scripts/{reference} or harness/scripts/{reference})"
                    )

    sub_agents = harness / "sub_agents"
    if sub_agents.is_dir():
        for directory in sorted(p for p in sub_agents.iterdir() if p.is_dir()):
            agent_md = directory / "AGENT.md"
            label = f"C5 subagent {directory.name}"
            if not agent_md.is_file():
                errors.append(f"{label}: missing AGENT.md")
                continue
            fields, _, problem = parse_frontmatter(read(agent_md))
            if problem:
                errors.append(f"{label}: {problem}")
                continue
            if fields.get("mode") != "subagent":
                errors.append(f"{label}: frontmatter needs 'mode: subagent'")
            if not fields.get("description"):
                errors.append(f"{label}: frontmatter description is required")

    plugins = harness / "plugin"
    if plugins.is_dir():
        for pattern in ("*.ts", "*.js", "*.mjs"):
            for path in sorted(plugins.glob(pattern)):
                label = f"C8 plugin {path.name}"
                text = read(path)
                if not text.strip():
                    errors.append(f"{label}: empty file; delete it or write the hook")
                elif not re.search(r"^export (const|default|async function)", text, re.MULTILINE):
                    errors.append(f"{label}: exports no plugin function (needs `export const` or `export default`)")

    scripts = harness / "scripts"
    if scripts.is_dir():
        for path in sorted(scripts.glob("*.py")):
            try:
                compile(read(path), str(path), "exec")
            except SyntaxError as error:
                errors.append(f"C7 script {path.name}: does not compile: {error}")
        for name in sorted(set(re.findall(r"scripts/([A-Za-z0-9_.\-]+\.py)", always_on_text))):
            if not (scripts / name).is_file():
                errors.append(f"C7: always-on text names scripts/{name} but harness/scripts/{name} does not exist")

    agents_md = root / "AGENTS.md"
    block = render_block(root)
    if active_always_on(root):
        mounted = read(agents_md) if agents_md.exists() else ""
        if BEGIN not in mounted or block not in mounted:
            errors.append("AGENTS.md managed block is missing or out of date; run: python3 tools/harness2.py mount")

    try:
        state = load_state(root)
    except HarnessError as error:
        errors.append(str(error))
        state = {"runtime": "opencode", "mounted": []}
    pairs = mount_pairs(root)
    for source, destination in pairs:
        if not destination.exists():
            errors.append(f"{rel(root, destination)} is not mounted (from {rel(root, source)}); run: python3 tools/harness2.py mount")
        elif destination.read_bytes() != source.read_bytes():
            errors.append(f"{rel(root, destination)} has drifted from {rel(root, source)}; edit harness/ and run mount")
    wanted = {rel(root, destination) for _, destination in pairs}
    for stale in sorted(set(state["mounted"]) - wanted):
        if (root / stale).exists():
            errors.append(f"{stale} is a stale mount; run: python3 tools/harness2.py mount")

    index = harness / LIBRARY / "index.md"
    if not index.is_file():
        errors.append(f"harness/{LIBRARY}/index.md is missing")
    else:
        entries = sorted(
            p for p in (harness / LIBRARY).glob("*/*") if p.is_dir()
        )
        for entry in entries:
            if not (entry / "EXPERIENCE.md").is_file():
                errors.append(f"harness/{LIBRARY}/{entry.parent.name}/{entry.name}: entry has no EXPERIENCE.md")
            if not (entry / "harness").is_dir():
                errors.append(f"harness/{LIBRARY}/{entry.parent.name}/{entry.name}: entry has no harness/ snapshot")

    return errors, warnings


def status_rows(root: Path) -> list[tuple[str, str, str, str]]:
    harness = harness_dir(root)
    pairs = mount_pairs(root)
    mounted = {rel(root, destination) for _, destination in pairs}
    agents_md = root / "AGENTS.md"
    agents_text = read(agents_md) if agents_md.exists() else ""
    rows: list[tuple[str, str, str, str]] = []

    for component in ALWAYS_ON:
        path = harness / component.path
        if not path.exists():
            state = "missing"
        elif STUB in read(path):
            state = "stub"
        elif f"<!-- {component.code} " in agents_text:
            state = "mounted in AGENTS.md"
        elif any(f"harness/{component.path}" in line for line in agents_text.splitlines()):
            state = "stale in AGENTS.md"
        else:
            state = "written, not mounted"
        rows.append((component.code, component.name, component.activation, state))

    skills = harness / "skills"
    skill_names = sorted(p.name for p in skills.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()) if skills.is_dir() else []
    sub_agents = harness / "sub_agents"
    agent_names = sorted(p.name for p in sub_agents.iterdir() if p.is_dir() and (p / "AGENT.md").is_file()) if sub_agents.is_dir() else []
    plugin_names = sorted(p.name for p in (harness / "plugin").glob("*.ts")) if (harness / "plugin").is_dir() else []
    script_names = sorted(p.name for p in (harness / "scripts").glob("*.py")) if (harness / "scripts").is_dir() else []

    def summarise(names: list[str], mounted_for) -> str:
        if not names:
            return "none"
        if mounted_for is None:
            return f"{len(names)}: {', '.join(names)}"
        present = sum(1 for name in names if any(mounted_for(name) == path for path in mounted))
        return f"{len(names)}: {', '.join(names)} ({present} mounted)"

    rows.append((
        "C6", "Skills", "skill tool",
        summarise(skill_names, lambda name: f"{MOUNT_TARGETS['skills']}/{name}/SKILL.md"),
    ))
    rows.append((
        "C5", "Subagents", "task tool",
        summarise(agent_names, lambda name: f"{MOUNT_TARGETS['sub_agents']}/{name}.md"),
    ))
    rows.append((
        "C8", "Plugin", "Inside the tool loop",
        summarise(plugin_names, lambda name: f"{MOUNT_TARGETS['plugin']}/{name}"),
    ))
    rows.append(("C7", "Scripts", "Run via bash", summarise(script_names, None)))

    library = harness / LIBRARY
    entries = [p for p in library.glob("*/*") if p.is_dir()] if library.is_dir() else []
    rows.append(("LIB", "Library", "Read by refinement", f"{len(entries)} entries"))
    return rows


def library_add(root: Path, domain: str, task: str, experience: Path, force: bool = False) -> list[str]:
    root = root.resolve()
    if not experience.is_file():
        raise SystemExit(f"experience file not found: {experience}")
    for label, value in (("domain", domain), ("task", task)):
        if not NAME_RE.fullmatch(value):
            raise SystemExit(f"invalid {label} '{value}': use lowercase letters, digits and single hyphens")
    library_root = harness_dir(root) / LIBRARY
    destination = (library_root / domain / task).resolve()
    if library_root.resolve() not in destination.parents:
        raise SystemExit(f"refusing to write outside harness/{LIBRARY}/")
    if destination.exists() and not force:
        raise SystemExit(f"{rel(root, destination)} already exists; pass --force to replace it")
    if destination.exists():
        shutil.rmtree(destination)
    snapshot = destination / "harness"
    snapshot.mkdir(parents=True)
    harness = harness_dir(root)
    for component in ALWAYS_ON:
        source = harness / component.path
        if not source.is_file():
            continue
        target = snapshot / component.path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for kind in (*MOUNTED, SCRIPTS):
        source = harness / kind.path
        if source.is_dir():
            shutil.copytree(source, snapshot / kind.path)
    shutil.copy2(experience, destination / "EXPERIENCE.md")

    index = harness / LIBRARY / "index.md"
    line = f"- `{domain}/{task}` — see `{domain}/{task}/EXPERIENCE.md`"
    text = read(index) if index.exists() else LIBRARY_INDEX
    if line not in text:
        if not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
        index.write_text(text, encoding="utf-8")
    return [f"{rel(root, destination)}: harness snapshot + EXPERIENCE.md", f"{rel(root, index)}: entry listed"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harness2 harness tooling")
    parser.add_argument("--repo", default=".", help="repository root (default: current directory)")
    commands = parser.add_subparsers(dest="command", required=True)

    scaffold_parser = commands.add_parser("scaffold", help="create the harness tree and library")
    scaffold_parser.add_argument("--force", action="store_true", help="overwrite existing component files")

    commands.add_parser("mount", help="sync harness components into the runtime")
    commands.add_parser("validate", help="run the harness gate")
    commands.add_parser("status", help="show component state")

    library_parser = commands.add_parser("library", help="harness improvement library")
    library_commands = library_parser.add_subparsers(dest="library_command", required=True)
    add_parser = library_commands.add_parser("add", help="add an adopted harness")
    add_parser.add_argument("--domain", required=True)
    add_parser.add_argument("--task", required=True)
    add_parser.add_argument("--experience", required=True)
    add_parser.add_argument("--force", action="store_true")

    arguments = parser.parse_args(argv)
    root = Path(arguments.repo).resolve()

    if arguments.command == "scaffold":
        created, skipped = ensure_stubs(root, arguments.force)
        for path in created:
            print(f"created {path}")
        for path in skipped:
            print(f"kept    {path}")
        try:
            for action in mount(root):
                print(action)
        except HarnessError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        errors, warnings = validate(root)
        for warning in warnings:
            print(f"warn: {warning}")
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        print("next: replace the stub files under harness/ with facts from this repository")
        return 1 if errors else 0

    if arguments.command == "mount":
        try:
            for action in mount(root):
                print(action)
        except HarnessError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        return 0

    if arguments.command == "validate":
        errors, warnings = validate(root)
        for warning in warnings:
            print(f"warn: {warning}")
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        if errors:
            print(f"harness gate failed: {len(errors)} error(s)", file=sys.stderr)
            return 1
        print(f"harness gate passed ({len(warnings)} warning(s))")
        return 0

    if arguments.command == "status":
        rows = status_rows(root)
        width = max(len(row[1]) for row in rows)
        for code, name, activation, state in rows:
            print(f"{code:<4} {name:<{width}}  {activation:<22}  {state}")
        return 0

    if arguments.command == "library":
        for action in library_add(root, arguments.domain, arguments.task, Path(arguments.experience), arguments.force):
            print(action)
        errors, warnings = validate(root)
        for warning in warnings:
            print(f"warn: {warning}")
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1 if errors else 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
