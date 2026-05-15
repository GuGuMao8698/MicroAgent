from __future__ import annotations

import json
from pathlib import Path

from ragflow_lite.agent_runtime.setup import (
    AgentRuntimePaths,
    setup_agent_runtime,
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
