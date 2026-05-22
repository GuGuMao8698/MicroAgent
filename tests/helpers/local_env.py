from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import MutableMapping

_PLACEHOLDER_ENV_VALUES = {
    "test-deepseek-api-key",
    "test-ark-api-key",
    "ep-test-model",
}


def load_export_env_file(
    path: Path,
    environ: MutableMapping[str, str] = os.environ,
) -> None:
    """Load simple `export NAME=value` entries from a local shell env file."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_export_assignment(raw_line)
        if parsed is None:
            continue
        name, value = parsed
        current = environ.get(name)
        if current is not None and current.strip() not in _PLACEHOLDER_ENV_VALUES:
            continue
        environ[name] = value


def _parse_export_assignment(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None

    parts = shlex.split(line, comments=True, posix=True)
    if not parts:
        return None
    if parts[0] == "export":
        parts = parts[1:]
    if len(parts) != 1 or "=" not in parts[0]:
        return None

    name, value = parts[0].split("=", 1)
    if not name or not name.replace("_", "").isalnum() or name[0].isdigit():
        return None
    return name, value
