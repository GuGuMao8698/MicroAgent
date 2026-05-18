from __future__ import annotations

import os
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
        microagent_dir=root / "src" / "ragflow_lite" / "microagent",
    )


def _write_microagent_bundle(paths: AgentRuntimePaths) -> None:
    (paths.microagent_dir / ".claude" / "skills" / "microrag-search").mkdir(
        parents=True
    )
    (paths.microagent_dir / ".claude" / "agents").mkdir(parents=True)
    (
        paths.microagent_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).write_text(
        "microagent skill\n",
        encoding="utf-8",
    )
    (paths.microagent_dir / ".claude" / "agents" / "hello-agent.md").write_text(
        "microagent agent\n",
        encoding="utf-8",
    )


def _write_legacy_runtime(paths: AgentRuntimePaths) -> Path:
    legacy_workspace = paths.project_root / "data" / "agent-runtime" / "workspace"
    (legacy_workspace / ".claude" / "skills" / "microrag-search").mkdir(parents=True)
    (legacy_workspace / ".claude" / "settings.json").write_text(
        '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
        encoding="utf-8",
    )
    (legacy_workspace / "CLAUDE.md").write_text(
        "# MicroRAG Product Agent\n",
        encoding="utf-8",
    )
    (
        legacy_workspace / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).write_text(
        "---\nname: microrag-search\n---\n# MicroRAG Search\n",
        encoding="utf-8",
    )
    return legacy_workspace


def test_setup_prepares_config_and_migrates_legacy_workspace_assets(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    _write_legacy_runtime(paths)

    setup_agent_runtime(paths)

    assert paths.config_dir.is_dir()
    assert (paths.workspace_dir / "CLAUDE.md").read_text(encoding="utf-8") == (
        "# MicroRAG Product Agent\n"
    )
    assert (
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).read_text(encoding="utf-8") == (
        "---\nname: microrag-search\n---\n# MicroRAG Search\n"
    )
    assert (paths.workspace_dir / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    ) == '{"permissions":{"defaultMode":"bypassPermissions"}}\n'


def test_setup_does_not_generate_product_claude_md_without_legacy_source(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    shim = paths.project_root / "data" / "agent-runtime" / "bin" / "mcrag"
    shim_text = shim.read_text(encoding="utf-8")

    assert paths.config_dir.is_dir()
    assert paths.workspace_dir.is_dir()
    assert shim.is_file()
    assert os.access(shim, os.X_OK)
    assert f'ROOT="{paths.project_root}"' in shim_text
    assert 'export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"' in shim_text
    assert "ragflow_lite.cli.mcrag" in shim_text
    assert not (paths.workspace_dir / "CLAUDE.md").exists()
    assert not paths.microagent_dir.exists()


def test_setup_does_not_create_or_overwrite_local_settings(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    settings_path = paths.microagent_dir / ".claude" / "settings.json"

    setup_agent_runtime(paths)

    assert not paths.microagent_dir.exists()
    assert not settings_path.exists()

    settings_path.parent.mkdir(parents=True)
    settings_path.write_text('{"permissions":{"defaultMode":"bypassPermissions"}}\n')
    setup_agent_runtime(paths)

    assert (
        settings_path.read_text(encoding="utf-8")
        == '{"permissions":{"defaultMode":"bypassPermissions"}}\n'
    )


def test_setup_does_not_generate_product_skill(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    assert not (paths.workspace_dir / ".claude" / "skills").exists()
    assert not paths.microagent_dir.exists()


def test_default_agent_runtime_paths_split_microagent_bundle_and_workspace(
    tmp_path: Path,
) -> None:
    paths = default_agent_runtime_paths(tmp_path)
    assert paths.project_root == tmp_path
    assert paths.config_dir == tmp_path / "data" / "agent-runtime" / "config"
    assert paths.workspace_dir == tmp_path / "data" / "agent-runtime" / "workspace"
    assert paths.microagent_dir == tmp_path / "src" / "ragflow_lite" / "microagent"


def test_default_agent_runtime_paths_honor_microagent_dir_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    microagent_dir = tmp_path / "external-microagent"
    monkeypatch.setenv("MICRORAG_MICROAGENT_DIR", str(microagent_dir))

    paths = default_agent_runtime_paths(tmp_path)

    assert paths.microagent_dir == microagent_dir
    assert paths.workspace_dir == tmp_path / "data" / "agent-runtime" / "workspace"


def test_default_agent_runtime_paths_honor_workspace_and_config_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace_dir = tmp_path / "external-workspace"
    config_dir = tmp_path / "external-config"
    monkeypatch.setenv("MICRORAG_AGENT_CWD", str(workspace_dir))
    monkeypatch.setenv("MICRORAG_AGENT_CONFIG_DIR", str(config_dir))

    paths = default_agent_runtime_paths(tmp_path)

    assert paths.workspace_dir == workspace_dir
    assert paths.config_dir == config_dir
    assert paths.microagent_dir == tmp_path / "src" / "ragflow_lite" / "microagent"


def test_setup_is_idempotent_and_does_not_overwrite_product_assets(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    (paths.workspace_dir / ".claude").mkdir(parents=True)
    (paths.workspace_dir / "CLAUDE.md").write_text(
        "# Product owned\n",
        encoding="utf-8",
    )
    (paths.workspace_dir / ".claude" / "settings.json").write_text(
        '{"product":true}\n',
        encoding="utf-8",
    )
    skill_path = (
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    )
    skill_path.parent.mkdir(parents=True)
    skill_path.write_text("product-owned skill", encoding="utf-8")

    setup_agent_runtime(paths)
    skill_path.write_text("existing product skill", encoding="utf-8")
    setup_agent_runtime(paths)
    assert skill_path.read_text(encoding="utf-8") == "existing product skill"
    assert (paths.workspace_dir / "CLAUDE.md").read_text(encoding="utf-8") == (
        "# Product owned\n"
    )
    assert (paths.workspace_dir / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    ) == '{"product":true}\n'
    assert not paths.microagent_dir.exists()


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


def test_validate_agent_runtime_workspace_requires_bundle_settings_after_setup(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    (paths.microagent_dir / ".claude" / "skills").mkdir(parents=True)
    (paths.microagent_dir / ".claude" / "agents").mkdir(parents=True)

    try:
        validate_agent_runtime_workspace(paths)
    except RuntimeError as exc:
        assert str(paths.microagent_dir / ".claude" / "settings.json") in str(exc)
    else:
        raise AssertionError("local MicroAgent settings must be required")


def test_validate_agent_runtime_workspace_succeeds_after_setup(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    _write_microagent_bundle(paths)
    (paths.microagent_dir / ".claude" / "settings.json").write_text(
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
    assert child_env["MICRORAG_AGENT_CWD"] == str(paths.workspace_dir)
    assert child_env["MICRORAG_AGENT_CONFIG_DIR"] == str(paths.config_dir)
    assert child_env["MICRORAG_MICROAGENT_DIR"] == str(paths.microagent_dir)
    assert child_env["PYTHONPATH"] == f"{paths.project_root / 'src'}:/existing/src"
    assert child_env["PATH"].startswith(str(paths.project_root / ".venv" / "bin"))
    assert child_env["PATH"].endswith(":/usr/bin")


def test_microagent_bundle_requires_skill_and_agent_directories(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    (paths.microagent_dir / ".claude" / "settings.json").parent.mkdir(parents=True)
    (paths.microagent_dir / ".claude" / "settings.json").write_text(
        '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
        encoding="utf-8",
    )
    setup_agent_runtime(paths)

    try:
        validate_agent_runtime_workspace(paths)
    except RuntimeError as exc:
        assert str(exc) == (
            "MicroRAG agent setup is incomplete. Runtime workspace is missing."
        )
    else:
        raise AssertionError("MicroAgent bundle must provide skills and agents")


def test_validate_agent_runtime_paths_accepts_default_paths(tmp_path: Path) -> None:
    paths = default_agent_runtime_paths(tmp_path)
    paths = setup_agent_runtime(paths)
    _write_microagent_bundle(paths)
    (paths.microagent_dir / ".claude" / "settings.json").write_text(
        '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
        encoding="utf-8",
    )
    from ragflow_lite.agent_runtime.setup import validate_agent_runtime_paths

    validate_agent_runtime_paths(paths)


def test_validate_agent_runtime_paths_rejects_repo_root_workspace(
    tmp_path: Path,
) -> None:
    from ragflow_lite.agent_runtime.setup import (
        SETUP_INCOMPLETE_MESSAGE,
        validate_agent_runtime_paths,
    )

    default_paths = default_agent_runtime_paths(tmp_path)
    default_paths = setup_agent_runtime(default_paths)
    _write_microagent_bundle(default_paths)
    repo_root_paths = AgentRuntimePaths(
        project_root=tmp_path,
        config_dir=default_paths.config_dir,
        workspace_dir=tmp_path,
        microagent_dir=default_paths.microagent_dir,
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

    paths = default_agent_runtime_paths(tmp_path)
    paths = setup_agent_runtime(paths)
    _write_microagent_bundle(paths)
    home_config_paths = AgentRuntimePaths(
        project_root=tmp_path,
        config_dir=Path.home() / ".claude",
        workspace_dir=paths.workspace_dir,
        microagent_dir=paths.microagent_dir,
    )

    try:
        validate_agent_runtime_paths(home_config_paths)
    except RuntimeError as exc:
        assert str(exc) == SETUP_INCOMPLETE_MESSAGE
    else:
        raise AssertionError("home config dir must be rejected")


def test_paths_helper_splits_microagent_bundle_and_workspace() -> None:
    paths = _paths(Path("/tmp"))

    assert paths.workspace_dir == (
        Path("/tmp") / "project" / "data" / "agent-runtime" / "workspace"
    )
    assert paths.microagent_dir == (
        Path("/tmp") / "project" / "src" / "ragflow_lite" / "microagent"
    )
