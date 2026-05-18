from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SETUP_INCOMPLETE_MESSAGE = (
    "MicroRAG agent setup is incomplete. Runtime workspace is missing."
)
LOCAL_SETTINGS_REQUIRED_MESSAGE = (
    "MicroRAG agent local settings are missing. Create "
    "{settings_path} before starting the agent."
)


@dataclass(frozen=True, slots=True)
class AgentRuntimePaths:
    project_root: Path
    config_dir: Path
    workspace_dir: Path
    microagent_dir: Path


def default_agent_runtime_paths(project_root: Path) -> AgentRuntimePaths:
    root = project_root.resolve()
    runtime_root = root / "data" / "agent-runtime"
    return AgentRuntimePaths(
        project_root=root,
        config_dir=_env_path_or_default(
            "MICRORAG_AGENT_CONFIG_DIR",
            runtime_root / "config",
        ),
        workspace_dir=_env_path_or_default(
            "MICRORAG_AGENT_CWD",
            runtime_root / "workspace",
        ),
        microagent_dir=_env_path_or_default(
            "MICRORAG_MICROAGENT_DIR",
            root / "src" / "ragflow_lite" / "microagent",
        ),
    )


def _env_path_or_default(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if value is not None and value.strip():
        return Path(value).expanduser()
    return default


def setup_agent_runtime(paths: AgentRuntimePaths) -> AgentRuntimePaths:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.workspace_dir.mkdir(parents=True, exist_ok=True)
    _write_mcrag_shim(paths)
    _migrate_legacy_workspace_assets(paths)
    return paths


def _runtime_bin_dir(paths: AgentRuntimePaths) -> Path:
    return paths.project_root / "data" / "agent-runtime" / "bin"


def _write_mcrag_shim(paths: AgentRuntimePaths) -> None:
    bin_dir = _runtime_bin_dir(paths)
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "mcrag"
    shim.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                f'ROOT="{paths.project_root}"',
                'export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"',
                'exec "$ROOT/.venv/bin/python" -m ragflow_lite.cli.mcrag "$@"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)


def _copy_if_missing(source: Path, target: Path) -> None:
    if not source.exists() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _copy_tree_files_if_missing(source_dir: Path, target_dir: Path) -> None:
    if not source_dir.is_dir():
        return
    for source in source_dir.rglob("*"):
        if not source.is_file():
            continue
        relative_path = source.relative_to(source_dir)
        _copy_if_missing(source, target_dir / relative_path)


def _migrate_legacy_workspace_assets(paths: AgentRuntimePaths) -> None:
    legacy_workspace = paths.project_root / "data" / "agent-runtime" / "workspace"
    if _same_path(legacy_workspace, paths.workspace_dir):
        return

    _copy_if_missing(
        legacy_workspace / ".claude" / "settings.json",
        paths.workspace_dir / ".claude" / "settings.json",
    )
    _copy_if_missing(
        legacy_workspace / "CLAUDE.md",
        paths.workspace_dir / "CLAUDE.md",
    )
    _copy_tree_files_if_missing(
        legacy_workspace / ".claude" / "skills",
        paths.workspace_dir / ".claude" / "skills",
    )


def _same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve() == right.expanduser().resolve()


def validate_agent_runtime_paths(paths: AgentRuntimePaths) -> None:
    expected = default_agent_runtime_paths(paths.project_root)
    if not _same_path(paths.config_dir, expected.config_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
    if not _same_path(paths.workspace_dir, expected.workspace_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
    if not _same_path(paths.microagent_dir, expected.microagent_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)


def validate_agent_runtime_workspace(paths: AgentRuntimePaths) -> None:
    validate_agent_runtime_paths(paths)
    microagent_claude_dir = paths.microagent_dir / ".claude"
    required = (
        paths.config_dir,
        paths.workspace_dir,
        paths.microagent_dir,
        microagent_claude_dir / "skills",
        microagent_claude_dir / "agents",
    )
    if not all(path.exists() for path in required):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
    settings_path = microagent_claude_dir / "settings.json"
    if not settings_path.exists():
        raise RuntimeError(
            LOCAL_SETTINGS_REQUIRED_MESSAGE.format(settings_path=settings_path)
        )


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
    env["MICRORAG_AGENT_CWD"] = str(paths.workspace_dir)
    env["MICRORAG_AGENT_CONFIG_DIR"] = str(paths.config_dir)
    env["MICRORAG_MICROAGENT_DIR"] = str(paths.microagent_dir)
    return env
