from __future__ import annotations

from pathlib import Path


def setup_test_agent_runtime(tmp_path: Path):
    from ragflow_lite.agent_runtime.setup import (
        default_agent_runtime_paths,
        setup_agent_runtime,
    )

    paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
    (paths.microagent_dir / ".claude" / "skills" / "microrag-search").mkdir(
        parents=True,
        exist_ok=True,
    )
    (paths.microagent_dir / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (paths.microagent_dir / ".claude" / "settings.json").write_text(
        '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
        encoding="utf-8",
    )
    (
        paths.microagent_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).write_text(
        "---\nname: microrag-search\n---\n# MicroRAG Search\n",
        encoding="utf-8",
    )
    return paths
