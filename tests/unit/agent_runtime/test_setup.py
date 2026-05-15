from __future__ import annotations

import json
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
    assert (paths.workspace_dir / ".claude" / "settings.json").is_file()
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


def test_product_settings_json_is_valid_and_retrieval_only(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    settings_text = (paths.workspace_dir / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    )
    settings = json.loads(settings_text)
    assert isinstance(settings, dict)
    assert "api_key" not in settings_text.lower()
    assert "secret" not in settings_text.lower()
    assert "mcrag retrieve" in settings_text
    assert "mcrag answer" not in settings_text


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


def test_validate_agent_runtime_workspace_succeeds_after_setup(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
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
