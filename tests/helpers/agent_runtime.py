from __future__ import annotations

from pathlib import Path


def setup_test_agent_runtime(tmp_path: Path):
    from ragflow_lite.agent_runtime.setup import (
        default_agent_runtime_paths,
        setup_agent_runtime,
    )

    paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
    (paths.workspace_dir / ".claude" / "skills" / "teach-me").mkdir(parents=True)
    (paths.workspace_dir / ".claude" / "agents").mkdir(parents=True)
    (paths.workspace_dir / ".claude" / "skills" / "teach-me" / "SKILL.md").write_text(
        "---\nname: teach-me\n---\n# Teach Me\n",
        encoding="utf-8",
    )
    (paths.workspace_dir / ".claude" / "agents" / "hello-agent.md").write_text(
        "---\nname: hello-agent\n---\nhello\n",
        encoding="utf-8",
    )
    (paths.workspace_dir / ".claude" / "settings.json").write_text(
        '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
        encoding="utf-8",
    )
    return paths
