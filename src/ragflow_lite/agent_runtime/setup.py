from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SETUP_INCOMPLETE_MESSAGE = (
    "MicroRAG agent setup is incomplete. Runtime workspace is missing."
)


@dataclass(frozen=True, slots=True)
class AgentRuntimePaths:
    project_root: Path
    config_dir: Path
    workspace_dir: Path


def default_agent_runtime_paths(project_root: Path) -> AgentRuntimePaths:
    root = project_root.resolve()
    runtime_root = root / "data" / "agent-runtime"
    return AgentRuntimePaths(
        project_root=root,
        config_dir=runtime_root / "config",
        workspace_dir=runtime_root / "workspace",
    )


def setup_agent_runtime(paths: AgentRuntimePaths) -> AgentRuntimePaths:
    source_root = Path(__file__).resolve().parent
    workspace = paths.workspace_dir
    claude_dir = workspace / ".claude"
    skill_dir = claude_dir / "skills" / "microrag-search"

    paths.config_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(source_root / "CLAUDE.md", workspace / "CLAUDE.md")
    shutil.copyfile(source_root / "settings.json", claude_dir / "settings.json")
    shutil.copyfile(
        source_root / "skills" / "microrag-search" / "SKILL.md",
        skill_dir / "SKILL.md",
    )
    return paths


def _same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve() == right.expanduser().resolve()


def validate_agent_runtime_paths(paths: AgentRuntimePaths) -> None:
    expected = default_agent_runtime_paths(paths.project_root)
    if not _same_path(paths.config_dir, expected.config_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
    if not _same_path(paths.workspace_dir, expected.workspace_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)


def validate_agent_runtime_workspace(paths: AgentRuntimePaths) -> None:
    validate_agent_runtime_paths(paths)
    required = (
        paths.config_dir,
        paths.workspace_dir / "CLAUDE.md",
        paths.workspace_dir / ".claude" / "settings.json",
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md",
    )
    if not all(path.exists() for path in required):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)


def build_agent_child_env(
    paths: AgentRuntimePaths,
    *,
    base_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    src_path = str(paths.project_root / "src")
    venv_bin = str(paths.project_root / ".venv" / "bin")

    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path
        if not existing_pythonpath
        else f"{src_path}{os.pathsep}{existing_pythonpath}"
    )

    existing_path = env.get("PATH")
    env["PATH"] = (
        venv_bin if not existing_path else f"{venv_bin}{os.pathsep}{existing_path}"
    )
    env["CLAUDE_CONFIG_DIR"] = str(paths.config_dir)
    return env
