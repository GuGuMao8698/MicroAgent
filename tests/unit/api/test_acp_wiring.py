"""Test ACP client wiring from Settings to AcpClient."""

from __future__ import annotations

from pathlib import Path

from ragflow_lite.agent_runtime.setup import (
    SETUP_INCOMPLETE_MESSAGE,
    AgentRuntimePaths,
    default_agent_runtime_paths,
    setup_agent_runtime,
)
from ragflow_lite.api.deps.providers import AppServices, _build_acp_client
from ragflow_lite.config.settings import Settings
from ragflow_lite.infrastructure.agent.acp_client import AcpClient, AcpRuntimeConfig


class TestBuildAcpClient:
    """Verify _build_acp_client constructs AcpClient from Settings."""

    def _make_settings(
        self,
        project_root: Path,
        *,
        agent_command: str = "claude",
        agent_args: str = "--acp",
        agent_cwd: str | None = None,
        agent_config_dir: str | None = None,
    ) -> Settings:
        return Settings(
            project_root=project_root,
            uploads_dir=project_root / "uploads",
            local_index_dir=project_root / "index",
            temp_dir=project_root / "tmp",
            deepseek_api_key="test-key",
            ark_api_key="test-ark-key",
            ark_embedding_model="test-model",
            agent_command=agent_command,
            agent_args=agent_args,
            agent_cwd=agent_cwd,
            agent_config_dir=agent_config_dir,
        )

    def test_constructs_acp_client_with_config_from_settings(
        self, tmp_path: Path
    ) -> None:
        from helpers.agent_runtime import setup_test_agent_runtime

        paths = setup_test_agent_runtime(tmp_path)
        settings = self._make_settings(
            tmp_path,
            agent_cwd=str(paths.workspace_dir),
            agent_config_dir=str(paths.config_dir),
        )
        client = _build_acp_client(settings)
        assert isinstance(client, AcpClient)

    def test_uses_custom_command_and_args(self, tmp_path: Path) -> None:
        from helpers.agent_runtime import setup_test_agent_runtime

        paths = setup_test_agent_runtime(tmp_path)
        settings = self._make_settings(
            tmp_path,
            agent_command="/usr/local/bin/agent",
            agent_args="--acp --verbose",
            agent_cwd=str(paths.workspace_dir),
            agent_config_dir=str(paths.config_dir),
        )
        client = _build_acp_client(settings)
        config = client._config
        assert isinstance(config, AcpRuntimeConfig)
        assert config.command == "/usr/local/bin/agent"
        assert config.args == ["--acp", "--verbose"]

    def test_requires_agent_runtime_workspace_when_cwd_missing(self) -> None:
        settings = self._make_settings(Path("/tmp/test-project"), agent_cwd=None)

        try:
            _build_acp_client(settings)
        except RuntimeError as exc:
            assert str(exc) == (
                "MicroRAG agent setup is incomplete. Runtime workspace is missing."
            )
        else:
            raise AssertionError("_build_acp_client should require runtime setup")

    def test_uses_explicit_cwd_when_set(self, tmp_path: Path) -> None:
        from helpers.agent_runtime import setup_test_agent_runtime

        paths = setup_test_agent_runtime(tmp_path)
        settings = self._make_settings(
            tmp_path,
            agent_cwd=str(paths.workspace_dir),
            agent_config_dir=str(paths.config_dir),
        )
        client = _build_acp_client(settings)
        assert client._config.cwd == str(paths.workspace_dir)

    def test_default_args_split_correctly(self, tmp_path: Path) -> None:
        from helpers.agent_runtime import setup_test_agent_runtime

        paths = setup_test_agent_runtime(tmp_path)
        settings = self._make_settings(
            tmp_path,
            agent_args="--acp",
            agent_cwd=str(paths.workspace_dir),
            agent_config_dir=str(paths.config_dir),
        )
        client = _build_acp_client(settings)
        assert client._config.args == ["--acp"]


def test_build_acp_client_sets_isolated_runtime_env(tmp_path: Path) -> None:
    from helpers.agent_runtime import setup_test_agent_runtime

    paths = setup_test_agent_runtime(tmp_path)
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "index",
        temp_dir=tmp_path / "tmp",
        deepseek_api_key="test-key",
        ark_api_key="test-ark-key",
        ark_embedding_model="test-model",
        agent_cwd=str(paths.workspace_dir),
        agent_config_dir=str(paths.config_dir),
    )

    client = _build_acp_client(settings)

    assert client._config.cwd == str(paths.workspace_dir)
    assert client._config.env["CLAUDE_CONFIG_DIR"] == str(paths.config_dir)
    assert str(tmp_path / "src") in client._config.env["PYTHONPATH"]
    assert str(tmp_path / ".venv" / "bin") in client._config.env["PATH"]


def test_settings_default_agent_runtime_paths() -> None:
    settings = Settings.default(Path("/tmp/test-project"))

    assert settings.agent_cwd == str(
        Path("/tmp/test-project") / "data" / "agent-runtime" / "workspace"
    )
    assert settings.agent_config_dir == str(
        Path("/tmp/test-project") / "data" / "agent-runtime" / "config"
    )
    assert settings.agent_args == "--acp --setting-sources project"


def test_app_services_acp_client_is_lazy(tmp_path: Path) -> None:
    calls: list[str] = []

    def factory() -> AcpClient:
        calls.append("called")
        return AcpClient(
            config=AcpRuntimeConfig(
                command="agent",
                args=["--acp"],
                cwd=str(tmp_path / "runtime"),
            )
        )

    services = AppServices(
        settings=Settings.default(tmp_path),
        agent_session_store=object(),
        acp_client_factory=factory,
        ingestion_pipeline=object(),
        retriever=object(),
        query_service=object(),
        discorag_query_service=object(),
        query_router=object(),
        document_service=object(),
        dataset_service=object(),
    )

    assert calls == []
    assert isinstance(services.acp_client, AcpClient)
    assert calls == ["called"]
    assert services.acp_client is services.acp_client
    assert calls == ["called"]


def test_build_acp_client_rejects_non_default_runtime_paths(tmp_path: Path) -> None:

    default_paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
    (default_paths.workspace_dir / ".claude" / "settings.json").write_text(
        '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
        encoding="utf-8",
    )
    rogue_workspace = tmp_path / "rogue-workspace"
    setup_agent_runtime(
        AgentRuntimePaths(
            project_root=tmp_path,
            config_dir=default_paths.config_dir,
            workspace_dir=rogue_workspace,
        )
    )
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "index",
        temp_dir=tmp_path / "tmp",
        deepseek_api_key="test-key",
        ark_api_key="test-ark-key",
        ark_embedding_model="test-model",
        agent_cwd=str(rogue_workspace),
        agent_config_dir=str(default_paths.config_dir),
    )

    try:
        _build_acp_client(settings)
    except RuntimeError as exc:
        assert str(exc) == SETUP_INCOMPLETE_MESSAGE
    else:
        raise AssertionError("non-default runtime workspace must be rejected")
