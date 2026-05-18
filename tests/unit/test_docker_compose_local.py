from pathlib import Path


def test_observability_app_sources_agent_runtime_local_env_before_uvicorn() -> None:
    compose = Path("docker/compose.local.yml").read_text(encoding="utf-8")

    assert "data/agent-runtime/local.env" in compose
    assert ". data/agent-runtime/local.env" in compose
    assert "exec uvicorn ragflow_lite.app:app" in compose
