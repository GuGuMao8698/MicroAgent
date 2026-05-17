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
        workspace_dir=root / "参考项目" / "claude-code",
    )


def _write_reference_runtime(paths: AgentRuntimePaths) -> None:
    (paths.workspace_dir / ".claude" / "skills" / "microrag-search").mkdir(parents=True)
    (paths.workspace_dir / ".claude" / "agents").mkdir(parents=True)
    (
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).write_text(
        "reference skill\n",
        encoding="utf-8",
    )
    (paths.workspace_dir / ".claude" / "agents" / "hello-agent.md").write_text(
        "reference agent\n",
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
    assert not (paths.workspace_dir / "CLAUDE.md").exists()


def test_setup_does_not_create_or_overwrite_local_settings(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    settings_path = paths.workspace_dir / ".claude" / "settings.json"

    setup_agent_runtime(paths)

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


def test_default_agent_runtime_paths_use_reference_claude_code_project(
    tmp_path: Path,
) -> None:
    paths = default_agent_runtime_paths(tmp_path)
    assert paths.project_root == tmp_path
    assert paths.config_dir == tmp_path / "data" / "agent-runtime" / "config"
    assert paths.workspace_dir == tmp_path / "参考项目" / "claude-code"


def test_default_agent_runtime_paths_honor_reference_runtime_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reference_runtime = tmp_path / "external-reference"
    monkeypatch.setenv("MICRORAG_REFERENCE_CLAUDE_CODE_DIR", str(reference_runtime))

    paths = default_agent_runtime_paths(tmp_path)

    assert paths.workspace_dir == reference_runtime


def test_setup_is_idempotent_and_overwrites_product_assets(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _write_reference_runtime(paths)
    (paths.workspace_dir / "CLAUDE.md").write_text(
        "# Reference owned\n",
        encoding="utf-8",
    )
    (paths.workspace_dir / ".claude" / "settings.json").write_text(
        '{"reference":true}\n',
        encoding="utf-8",
    )
    _write_legacy_runtime(paths)
    setup_agent_runtime(paths)
    skill_path = (
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    )
    skill_path.write_text("reference-owned skill", encoding="utf-8")
    setup_agent_runtime(paths)
    assert skill_path.read_text(encoding="utf-8") == "reference-owned skill"
    assert (paths.workspace_dir / "CLAUDE.md").read_text(encoding="utf-8") == (
        "# Reference owned\n"
    )
    assert (paths.workspace_dir / ".claude" / "settings.json").read_text(
        encoding="utf-8"
    ) == '{"reference":true}\n'


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
    _write_reference_runtime(paths)
    setup_agent_runtime(paths)

    try:
        validate_agent_runtime_workspace(paths)
    except RuntimeError as exc:
        assert "参考项目/claude-code/.claude/settings.json" in str(exc)
    else:
        raise AssertionError("local runtime settings must be required")


def test_validate_agent_runtime_workspace_succeeds_after_setup(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    _write_reference_runtime(paths)
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


def test_reference_runtime_requires_skill_and_agent_directories(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    (paths.workspace_dir / ".claude" / "settings.json").parent.mkdir(parents=True)
    (paths.workspace_dir / ".claude" / "settings.json").write_text(
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
        raise AssertionError("reference runtime must provide skills and agents")


def test_validate_agent_runtime_paths_accepts_default_paths(tmp_path: Path) -> None:
    paths = default_agent_runtime_paths(tmp_path)
    _write_reference_runtime(paths)
    paths = setup_agent_runtime(paths)
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
    _write_reference_runtime(default_paths)
    default_paths = setup_agent_runtime(default_paths)
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

    paths = default_agent_runtime_paths(tmp_path)
    _write_reference_runtime(paths)
    paths = setup_agent_runtime(paths)
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


def test_paths_helper_points_to_reference_runtime() -> None:
    paths = _paths(Path("/tmp"))

    assert paths.workspace_dir == Path("/tmp") / "project" / "参考项目" / "claude-code"
