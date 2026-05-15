from __future__ import annotations

from pathlib import Path


def setup_test_agent_runtime(tmp_path: Path):
    from ragflow_lite.agent_runtime.setup import (
        default_agent_runtime_paths,
        setup_agent_runtime,
    )

    return setup_agent_runtime(default_agent_runtime_paths(tmp_path))
