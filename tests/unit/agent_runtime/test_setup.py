from __future__ import annotations

from pathlib import Path

from ragflow_lite.agent_runtime.setup import (
    AgentRuntimePaths,
    build_agent_child_env,
    default_agent_runtime_paths,
    setup_agent_runtime,
    validate_agent_runtime_workspace,
)


def _paths(tmp_path: Path) -> AgentRuntimePaths:
    root = tmp_path / "project"
    return AgentRuntimePaths(
        project_root=root,
        config_dir=root / "data" / "agent-runtime" / "config",
        workspace_dir=root / "data" / "agent-runtime" / "workspace",
    )


def test_setup_writes_runtime_workspace_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    assert paths.config_dir.is_dir()
    assert (paths.workspace_dir / "CLAUDE.md").is_file()
    assert (
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).is_file()


def test_product_claude_md_excludes_developer_workflow_terms(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    text = (paths.workspace_dir / "CLAUDE.md").read_text(encoding="utf-8")
    forbidden = (
        "AGENTS.md",
        "CONTRACTS.md",
        "cx ",
        "pytest",
        "git workflow",
        "code-review",
        "Claude Code",
    )
    assert all(term not in text for term in forbidden)
    assert "MicroRAG" in text
    assert "microrag-search" in text


def test_setup_does_not_create_or_overwrite_local_settings(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    settings_path = paths.workspace_dir / ".claude" / "settings.json"

    setup_agent_runtime(paths)

    assert not settings_path.exists()

    settings_path.write_text('{"permissions":{"defaultMode":"bypassPermissions"}}\n')
    setup_agent_runtime(paths)

    assert (
        settings_path.read_text(encoding="utf-8")
        == '{"permissions":{"defaultMode":"bypassPermissions"}}\n'
    )


def test_product_skill_is_find_docs_style_discorag_only(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    skill = (
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "## Workflow" in skill
    assert "## Retrieve Evidence" in skill
    assert "## Error Handling" in skill
    assert "## Common Mistakes" in skill
    assert "mcrag retrieve" in skill
    assert "--mode discorag" in skill
    assert "--mode standard" not in skill
    assert "mcrag answer" not in skill
    assert "stderr diagnostics are not evidence" in skill


def test_default_agent_runtime_paths_use_data_agent_runtime(tmp_path: Path) -> None:
    paths = default_agent_runtime_paths(tmp_path)
    assert paths.project_root == tmp_path
    assert paths.config_dir == tmp_path / "data" / "agent-runtime" / "config"
    assert paths.workspace_dir == tmp_path / "data" / "agent-runtime" / "workspace"


def test_setup_is_idempotent_and_overwrites_product_assets(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    skill_path = (
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    )
    skill_path.write_text("stale local copy", encoding="utf-8")
    setup_agent_runtime(paths)
    assert "stale local copy" not in skill_path.read_text(encoding="utf-8")
    assert "--mode discorag" in skill_path.read_text(encoding="utf-8")


def test_validate_agent_runtime_workspace_fails_with_product_message(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    try:
        validate_agent_runtime_workspace(paths)
    except RuntimeError as exc:
        assert str(exc) == (
            "MicroRAG agent setup is incomplete. Runtime workspace is missing."
        )
    else:
        raise AssertionError("validate_agent_runtime_workspace should fail")


def test_validate_agent_runtime_workspace_requires_local_settings_after_setup(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)

    try:
        validate_agent_runtime_workspace(paths)
    except RuntimeError as exc:
        assert "data/agent-runtime/workspace/.claude/settings.json" in str(exc)
    else:
        raise AssertionError("local runtime settings must be required")


def test_validate_agent_runtime_workspace_succeeds_after_setup(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    (paths.workspace_dir / ".claude" / "settings.json").write_text(
        '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
        encoding="utf-8",
    )
    validate_agent_runtime_workspace(paths)


def test_build_agent_child_env_sets_config_path_and_python_access(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    base_env = {"PATH": "/usr/bin", "PYTHONPATH": "/existing/src", "KEEP": "1"}
    child_env = build_agent_child_env(paths, base_env=base_env)
    assert child_env["KEEP"] == "1"
    assert child_env["CLAUDE_CONFIG_DIR"] == str(paths.config_dir)
    assert child_env["PYTHONPATH"] == f"{paths.project_root / 'src'}:/existing/src"
    assert child_env["PATH"].startswith(str(paths.project_root / ".venv" / "bin"))
    assert child_env["PATH"].endswith(":/usr/bin")


def test_repository_skill_matches_product_discorag_contract() -> None:
    repo_skill = Path(".claude/skills/microrag-search/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "## Workflow" in repo_skill
    assert "mcrag retrieve" in repo_skill
    assert "--mode discorag" in repo_skill
    assert "--mode standard" not in repo_skill
    assert "mcrag answer" not in repo_skill


def test_validate_agent_runtime_paths_accepts_default_paths(tmp_path: Path) -> None:
    paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
    from ragflow_lite.agent_runtime.setup import validate_agent_runtime_paths

    validate_agent_runtime_paths(paths)


def test_validate_agent_runtime_paths_rejects_repo_root_workspace(
    tmp_path: Path,
) -> None:
    from ragflow_lite.agent_runtime.setup import (
        SETUP_INCOMPLETE_MESSAGE,
        validate_agent_runtime_paths,
    )

    default_paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
    repo_root_paths = AgentRuntimePaths(
        project_root=tmp_path,
        config_dir=default_paths.config_dir,
        workspace_dir=tmp_path,
    )

    try:
        validate_agent_runtime_paths(repo_root_paths)
    except RuntimeError as exc:
        assert str(exc) == SETUP_INCOMPLETE_MESSAGE
    else:
        raise AssertionError("repo root workspace must be rejected")


def test_validate_agent_runtime_paths_rejects_home_config_dir(
    tmp_path: Path,
) -> None:
    from ragflow_lite.agent_runtime.setup import (
        SETUP_INCOMPLETE_MESSAGE,
        validate_agent_runtime_paths,
    )

    paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
    home_config_paths = AgentRuntimePaths(
        project_root=tmp_path,
        config_dir=Path.home() / ".claude",
        workspace_dir=paths.workspace_dir,
    )

    try:
        validate_agent_runtime_paths(home_config_paths)
    except RuntimeError as exc:
        assert str(exc) == SETUP_INCOMPLETE_MESSAGE
    else:
        raise AssertionError("home config dir must be rejected")


def test_source_claude_template_is_behavior_only() -> None:
    template = Path("src/ragflow_lite/agent_runtime/CLAUDE.md")
    text = template.read_text(encoding="utf-8")

    assert "You are MicroRAG's product conversation agent" not in text
    assert "Use MicroRAG retrieval" in text
    assert "Answer from retrieved evidence" in text
    assert "Do not expose runtime internals" in text
    assert "Do not invent evidence" in text


def test_setup_copies_behavior_only_claude_md(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)

    text = (paths.workspace_dir / "CLAUDE.md").read_text(encoding="utf-8")
    assert "You are MicroRAG's product conversation agent" not in text
    assert "Use MicroRAG retrieval" in text
    assert "Answer from retrieved evidence" in text
    assert "Do not expose runtime internals" in text
    assert "Do not invent evidence" in text


def test_product_skill_uses_case_insensitive_setup_error_guidance(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    skill = (
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "reports a setup error" in skill
    assert "`setup error:`" not in skill
