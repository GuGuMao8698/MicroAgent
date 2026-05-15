"""Test ACP client wiring from Settings to AcpClient."""

from __future__ import annotations

from pathlib import Path

from ragflow_lite.api.deps.providers import _build_acp_client
from ragflow_lite.config.settings import Settings
from ragflow_lite.infrastructure.agent.acp_client import AcpClient, AcpRuntimeConfig


class TestBuildAcpClient:
    """Verify _build_acp_client constructs AcpClient from Settings."""

    def _make_settings(
        self,
        *,
        agent_command: str = "claude",
        agent_args: str = "--acp",
        agent_cwd: str | None = None,
    ) -> Settings:
        return Settings(
            project_root=Path("/tmp/test-project"),
            uploads_dir=Path("/tmp/test-uploads"),
            local_index_dir=Path("/tmp/test-index"),
            temp_dir=Path("/tmp/test-tmp"),
            deepseek_api_key="test-key",
            ark_api_key="test-ark-key",
            ark_embedding_model="test-model",
            agent_command=agent_command,
            agent_args=agent_args,
            agent_cwd=agent_cwd,
        )

    def test_constructs_acp_client_with_config_from_settings(self) -> None:
        settings = self._make_settings()
        client = _build_acp_client(settings)
        assert isinstance(client, AcpClient)

    def test_uses_custom_command_and_args(self) -> None:
        settings = self._make_settings(
            agent_command="/usr/local/bin/agent", agent_args="--acp --verbose"
        )
        client = _build_acp_client(settings)
        config = client._config
        assert isinstance(config, AcpRuntimeConfig)
        assert config.command == "/usr/local/bin/agent"
        assert config.args == ["--acp", "--verbose"]

    def test_falls_back_to_project_root_when_cwd_not_set(self) -> None:
        settings = self._make_settings(agent_cwd=None)
        client = _build_acp_client(settings)
        assert client._config.cwd == "/tmp/test-project"

    def test_uses_explicit_cwd_when_set(self) -> None:
        settings = self._make_settings(agent_cwd="/custom/workdir")
        client = _build_acp_client(settings)
        assert client._config.cwd == "/custom/workdir"

    def test_default_args_split_correctly(self) -> None:
        settings = self._make_settings(agent_args="--acp")
        client = _build_acp_client(settings)
        assert client._config.args == ["--acp"]
