#!/usr/bin/env python3
"""Tests for tools/harness2.py: scaffold, mount, validate, library."""

import contextlib
import importlib.machinery
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
TOOL = ROOT / "tools" / "harness2.py"
SHIPPED = ROOT / ".opencode" / "skills" / "harness2" / "scripts" / "harness2.py"

loader = importlib.machinery.SourceFileLoader("harness2", str(TOOL))
spec = importlib.util.spec_from_loader(loader.name, loader)
tool = importlib.util.module_from_spec(spec)
sys.modules[loader.name] = tool
loader.exec_module(tool)

assert SHIPPED.is_file(), "the harness2 skill ships its own copy of the tool"
assert SHIPPED.read_bytes() == TOOL.read_bytes(), "skill copy has drifted from tools/harness2.py"

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    (repo / "AGENTS.md").write_text("# Project\n\nKeep this line.\n")

    created, _ = tool.ensure_stubs(repo)
    assert "harness/systemprompt.md" in created
    assert "harness/library/index.md" in created
    assert (repo / "harness" / "skills" / "README.md").is_file()

    tool.mount(repo)
    errors, warnings = tool.validate(repo)
    assert not errors, errors
    assert sum("still a stub" in warning for warning in warnings) == 4, warnings
    agents = (repo / "AGENTS.md").read_text()
    assert "Keep this line." in agents, "mount must not drop existing AGENTS.md content"
    assert tool.BEGIN in agents and tool.END in agents
    assert "C1 System prompt" not in agents, "stub components must not reach the agent"

    (repo / "harness" / "systemprompt.md").write_text(
        "# Prompt\n\nWhen you audit a deploy, load the `deploy-audit` skill.\n"
    )
    skill = repo / "harness" / "skills" / "deploy-audit"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: deploy-audit\ndescription: Audit the deploy surface.\n---\n\n"
        "Run `python3 harness/scripts/audit.py`.\n"
    )
    (repo / "harness" / "scripts" / "audit.py").write_text('print("ok")\n')
    agent = repo / "harness" / "sub_agents" / "surface"
    agent.mkdir(parents=True)
    (agent / "AGENT.md").write_text(
        "---\ndescription: Reads the deploy recipe.\nmode: subagent\n---\n\nReturn a table.\n"
    )
    tool.mount(repo)
    errors, warnings = tool.validate(repo)
    assert not errors, errors
    assert (repo / ".opencode" / "skills" / "deploy-audit" / "SKILL.md").is_file()
    assert (repo / ".opencode" / "agents" / "surface.md").is_file()
    assert "C1 System prompt" in (repo / "AGENTS.md").read_text()
    assert "deploy-audit" in (repo / "AGENTS.md").read_text()

    def problems():
        return tool.validate(repo)[0]

    def expect(fragment, action):
        action()
        found = problems()
        assert any(fragment in problem for problem in found), (fragment, found)

    skill_md = skill / "SKILL.md"
    original_skill = skill_md.read_text()
    original_prompt = (repo / "harness" / "systemprompt.md").read_text()

    (repo / ".opencode" / "skills" / "deploy-audit" / "SKILL.md").write_text("tampered\n")
    expect("drifted", lambda: None)
    tool.mount(repo)

    expect(
        "trigger line",
        lambda: (repo / "harness" / "systemprompt.md").write_text("# Prompt\n"),
    )
    (repo / "harness" / "systemprompt.md").write_text(original_prompt)

    expect(
        "trigger line",
        lambda: (repo / "harness" / "systemprompt.md").write_text(
            "# Prompt\n\nSee deploy-audit for details.\n"
        ),
    )
    (repo / "harness" / "systemprompt.md").write_text(original_prompt)

    expect(
        "duplicate frontmatter key",
        lambda: skill_md.write_text(
            "---\nname: deploy-audit\ndescription: Audit.\ndescription: Audit again.\n---\n\n"
            "Run `python3 harness/scripts/audit.py`.\n"
        ),
    )
    skill_md.write_text(original_skill)

    expect("no such file", lambda: (repo / "harness" / "scripts" / "audit.py").unlink())
    (repo / "harness" / "scripts" / "audit.py").write_text('print("ok")\n')

    guardrails = repo / "harness" / "guardrails.md"
    expect(
        "template brace",
        lambda: guardrails.write_text("# Guardrails\n\nNever use {{ here }}.\n"),
    )
    guardrails.write_text("# Guardrails\n\nNo credentials.\n")

    expect(
        "name must be 'deploy-audit'",
        lambda: skill_md.write_text(
            "---\nname: other\ndescription: Audit.\n---\n\nRun `python3 harness/scripts/audit.py`.\n"
        ),
    )
    skill_md.write_text(original_skill)

    expect(
        "mode: subagent",
        lambda: (agent / "AGENT.md").write_text("---\ndescription: Reads.\n---\n\nTable.\n"),
    )
    (agent / "AGENT.md").write_text(
        "---\ndescription: Reads the deploy recipe.\nmode: subagent\n---\n\nReturn a table.\n"
    )

    expect(
        "does not compile",
        lambda: (repo / "harness" / "scripts" / "audit.py").write_text("def broken(:\n"),
    )
    (repo / "harness" / "scripts" / "audit.py").write_text('print("ok")\n')

    tool.mount(repo)
    assert not problems(), problems()

    # a removed component is pruned from the runtime
    surface_mount = repo / ".opencode" / "agents" / "surface.md"
    assert surface_mount.is_file()
    (agent / "AGENT.md").unlink()
    agent.rmdir()
    tool.mount(repo)
    assert not surface_mount.exists(), "stale mounts must be pruned"
    assert not problems(), problems()

    experience = repo / "EXPERIENCE.md"
    experience.write_text("# Experience\n\nSituation: deploy audit.\n")
    tool.library_add(repo, "ops", "audit-deploy", experience)
    assert (repo / "harness" / "library" / "ops" / "audit-deploy" / "EXPERIENCE.md").is_file()
    assert (repo / "harness" / "library" / "ops" / "audit-deploy" / "harness" / "systemprompt.md").is_file()
    assert "ops/audit-deploy" in (repo / "harness" / "library" / "index.md").read_text()
    errors, warnings = tool.validate(repo)
    assert not errors, errors

    rows = tool.status_rows(repo)
    assert [row[0] for row in rows] == ["C1", "C2", "C3", "C4", "C6", "C5", "C8", "C7", "LIB"]
    assert "mounted in AGENTS.md" in [row[3] for row in rows][0], rows

    # a corrupt state file fails closed instead of silently losing pruning
    state_file = repo / "harness" / ".mount-state.json"
    original_state = state_file.read_text()
    state_file.write_text("{not json")
    assert any("corrupt" in error for error in tool.validate(repo)[0])
    try:
        tool.mount(repo)
    except tool.HarnessError as error:
        assert "corrupt" in str(error), error
    else:
        raise AssertionError("mount must refuse a corrupt state file")
    state_file.write_text(original_state)

    # an unpaired managed marker must not truncate AGENTS.md
    agents_file = repo / "AGENTS.md"
    original_agents = agents_file.read_text()
    agents_file.write_text(original_agents.replace(tool.END, ""))
    try:
        tool.mount(repo)
    except tool.HarnessError as error:
        assert "unpaired" in str(error), error
    else:
        raise AssertionError("mount must refuse an unpaired marker")
    agents_file.write_text(original_agents)

    # library names cannot escape the library directory
    try:
        tool.library_add(repo, "../escape", "task", experience)
    except SystemExit as error:
        assert "invalid domain" in str(error), error
    else:
        raise AssertionError("library_add must reject a traversal domain")
    assert not (repo.parent / "escape").exists()

    # plugins mount and prune like every other on-demand component
    plugin = repo / "harness" / "plugin" / "guard.ts"
    plugin.write_text("export const Guard = async () => ({})\n")
    tool.mount(repo)
    assert (repo / ".opencode" / "plugins" / "guard.ts").is_file()
    assert not tool.validate(repo)[0], tool.validate(repo)[0]
    plugin.unlink()
    tool.mount(repo)
    assert not (repo / ".opencode" / "plugins" / "guard.ts").exists()

    # mount is idempotent
    assert tool.mount(repo) == ["AGENTS.md: always-on block unchanged"], tool.mount(repo)

    # the CLI wiring returns the gate's exit code
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert tool.main(["--repo", str(repo), "validate"]) == 0
        (repo / "harness" / "systemprompt.md").write_text("# Prompt\n")
        assert tool.main(["--repo", str(repo), "validate"]) == 1
        assert tool.main(["--repo", str(repo), "status"]) == 0

print("harness2 checks passed")
