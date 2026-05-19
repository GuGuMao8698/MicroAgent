# MicroRAG Agent Runtime Workspace Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Isolate the product-facing agent runtime from repository-root developer Claude configuration by generating a dedicated runtime workspace and starting ACP with that workspace and config directory.

**Architecture:** Add source-controlled product runtime assets under `src/ragflow_lite/agent_runtime/`, then generate ignored runtime files under `data/agent-runtime/` with `mcrag agent setup`. Extend ACP runtime config so the child process receives `CLAUDE_CONFIG_DIR`, `PATH`, and `PYTHONPATH`, and change default ACP cwd from repository root to `data/agent-runtime/workspace`.

**Tech Stack:** Python 3.13, stdlib `argparse`, stdlib `json`, stdlib `dataclasses`, stdlib `pathlib`, stdlib `shutil`, stdlib `subprocess`, pytest, existing MicroRAG `Settings`, `AcpClient`, and `mcrag` CLI.

---

Date: 2026-05-15
Status: Ready for implementation after confirmation
Spec:
[../specs/2026-05-15-microrag-agent-runtime-workspace-isolation.md](../specs/2026-05-15-microrag-agent-runtime-workspace-isolation.md)

## File Structure

Files to create:

- `src/ragflow_lite/agent_runtime/__init__.py`
  - Public helpers for product agent runtime workspace setup.
- `src/ragflow_lite/agent_runtime/setup.py`
  - Path calculation, template copy, validation, and child-process environment helpers.
- `src/ragflow_lite/agent_runtime/CLAUDE.md`
  - Product-only agent instructions. No repository development rules.
- `src/ragflow_lite/agent_runtime/settings.json`
  - Product-only project settings. Allows only the first-stage retrieval command surface.
- `src/ragflow_lite/agent_runtime/skills/microrag-search/SKILL.md`
  - Find Docs-style, DiscoRAG-only retrieval skill.
- `tests/unit/agent_runtime/test_setup.py`
  - Runtime setup, generated file, isolation, and child environment tests.

Files to modify:

- `pyproject.toml`
  - Include product runtime assets as package data.
- `src/ragflow_lite/cli/mcrag.py`
  - Add `mcrag agent setup`; avoid creating runtime services for setup commands.
- `src/ragflow_lite/config/settings.py`
  - Add agent runtime config directory and default runtime cwd values.
- `src/ragflow_lite/infrastructure/agent/acp_client.py`
  - Add child process env support to `AcpRuntimeConfig` and `_default_process_factory`.
- `src/ragflow_lite/api/deps/providers.py`
  - Build `AcpClient` with isolated cwd, `CLAUDE_CONFIG_DIR`, `PATH`, and `PYTHONPATH`; fail clearly when setup is missing.
- `src/ragflow_lite/infrastructure/CONTRACTS.md`
  - Replace stale project-root fallback contract with active runtime workspace contract.
- `tests/unit/cli/test_mcrag_cli.py`
  - Cover `mcrag agent setup` and setup commands that do not require provider services.
- `tests/unit/api/test_acp_wiring.py`
  - Cover isolated cwd, config env, path env, and missing setup failure.
- `tests/unit/infrastructure/test_acp_client_redaction.py`
  - Cover child process env injection without weakening redaction tests.

## Implementation Notes

- Use `rtk` for shell commands in this repository.
- Keep `data/agent-runtime/` ignored. Runtime files are generated artifacts, not source of truth.
- Keep source-controlled assets under `src/ragflow_lite/agent_runtime/`.
- Do not use repository-root `.claude/settings.json` or `~/.claude/settings.json`.
- Do not put `mcrag answer` in the product `microrag-search` skill.
- Do not put `--mode standard` in the product `microrag-search` skill.
- Do not mention `AGENTS.md`, `CONTRACTS.md`, `cx`, pytest, git workflow, or code-review workflow in product runtime assets.
- Keep `mcrag retrieve` and `mcrag answer` CLI behavior intact. This plan only changes the product skill surface.
- The existing `agent_args` parser uses whitespace splitting. Keep first-stage default args simple: `--acp --setting-sources project,local`.
- If a selected runtime does not support `--setting-sources`, operators can set `MICRORAG_AGENT_ARGS=--acp`; this fallback must be documented in the infrastructure contract.

## Task 0: Baseline Preflight

Purpose: confirm the workspace starts from the expected merged agent shell state before runtime isolation edits.

**Files:**
- Read: `docs/superpowers/specs/2026-05-15-microrag-agent-runtime-workspace-isolation.md`
- Read: `src/ragflow_lite/infrastructure/agent/acp_client.py`
- Read: `src/ragflow_lite/api/deps/providers.py`
- Read: `src/ragflow_lite/config/settings.py`
- Read: `src/ragflow_lite/cli/mcrag.py`
- Read: `tests/unit/api/test_acp_wiring.py`
- Read: `tests/unit/cli/test_mcrag_cli.py`

- [ ] **Step 1: Check branch and working tree**

Run:

```bash
rtk git status --short --branch
```

Expected:

```text
## main...origin/main
```

`docs/superpowers/` may be ignored, so existing spec/plan files may not appear in status.

- [ ] **Step 2: Confirm current ACP fallback still points to project root**

Run:

```bash
cx definition --name _build_acp_client --from src/ragflow_lite/api/deps/providers.py
```

Expected current code contains:

```python
agent_cwd = settings.agent_cwd or str(settings.project_root)
```

- [ ] **Step 3: Run focused current tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_acp_wiring.py tests/unit/cli/test_mcrag_cli.py -q
```

Expected: tests pass before edits.

## Task 1: Add Product Runtime Assets

Purpose: add source-controlled product runtime templates with a DiscoRAG-only skill.

**Files:**
- Create: `src/ragflow_lite/agent_runtime/__init__.py`
- Create: `src/ragflow_lite/agent_runtime/CLAUDE.md`
- Create: `src/ragflow_lite/agent_runtime/settings.json`
- Create: `src/ragflow_lite/agent_runtime/skills/microrag-search/SKILL.md`
- Modify: `pyproject.toml`
- Test: `tests/unit/agent_runtime/test_setup.py`

- [ ] **Step 1: Write failing asset-content tests**

Create `tests/unit/agent_runtime/test_setup.py` with:

```python
from __future__ import annotations

import json
from pathlib import Path

from ragflow_lite.agent_runtime.setup import (
    AgentRuntimePaths,
    setup_agent_runtime,
)


def _paths(tmp_path: Path) -> AgentRuntimePaths:
    root = tmp_path / "project"
    return AgentRuntimePaths(
        project_root=root,
        config_dir=root / "data" / "agent-runtime" / "config",
        workspace_dir=root / "data" / "agent-runtime" / "workspace",
    )


def test_setup_writes_runtime_workspace_files(tmp_path: Path) -> None:
    paths = _paths(tmp_path)

    setup_agent_runtime(paths)

    assert paths.config_dir.is_dir()
    assert (paths.workspace_dir / "CLAUDE.md").is_file()
    assert (paths.workspace_dir / ".claude" / "settings.json").is_file()
    assert (
        paths.workspace_dir
        / ".claude"
        / "skills"
        / "microrag-search"
        / "SKILL.md"
    ).is_file()


def test_product_claude_md_excludes_developer_workflow_terms(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)

    text = (paths.workspace_dir / "CLAUDE.md").read_text(encoding="utf-8")

    forbidden = (
        "AGENTS.md",
        "CONTRACTS.md",
        "cx ",
        "pytest",
        "git workflow",
        "code-review",
        "Claude Code",
    )
    assert all(term not in text for term in forbidden)
    assert "MicroRAG" in text
    assert "microrag-search" in text


def test_product_settings_json_is_valid_and_retrieval_only(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)

    settings_text = (
        paths.workspace_dir / ".claude" / "settings.json"
    ).read_text(encoding="utf-8")
    settings = json.loads(settings_text)

    assert isinstance(settings, dict)
    assert "api_key" not in settings_text.lower()
    assert "secret" not in settings_text.lower()
    assert "mcrag retrieve" in settings_text
    assert "mcrag answer" not in settings_text


def test_product_skill_is_find_docs_style_discorag_only(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)

    skill = (
        paths.workspace_dir
        / ".claude"
        / "skills"
        / "microrag-search"
        / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "## Workflow" in skill
    assert "## Retrieve Evidence" in skill
    assert "## Error Handling" in skill
    assert "## Common Mistakes" in skill
    assert "mcrag retrieve" in skill
    assert "--mode discorag" in skill
    assert "--mode standard" not in skill
    assert "mcrag answer" not in skill
    assert "stderr diagnostics are not evidence" in skill
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/agent_runtime/test_setup.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'ragflow_lite.agent_runtime'`.

- [ ] **Step 3: Add source-controlled product assets**

Create `src/ragflow_lite/agent_runtime/__init__.py`:

```python
"""Product agent runtime assets and workspace setup helpers."""

from ragflow_lite.agent_runtime.setup import (
    AgentRuntimePaths,
    default_agent_runtime_paths,
    setup_agent_runtime,
)

__all__ = [
    "AgentRuntimePaths",
    "default_agent_runtime_paths",
    "setup_agent_runtime",
]
```

Create `src/ragflow_lite/agent_runtime/CLAUDE.md`:

```markdown
# MicroRAG Product Agent

You are MicroRAG's product conversation agent.

Use MicroRAG retrieval when the user asks about indexed local documents or when
document evidence is needed. Prefer the `microrag-search` skill for document
search.

Answer from retrieved evidence. If retrieval fails or the evidence is
insufficient, say that MicroRAG did not find enough evidence and ask the user to
clarify the question.

Do not expose runtime internals, command lines, local filesystem paths,
transcript files, process protocol details, provider branding, or developer
workflow details.

Do not invent evidence, citations, document facts, or source claims.
```

Create `src/ragflow_lite/agent_runtime/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(mcrag retrieve:*)"
    ]
  }
}
```

Create `src/ragflow_lite/agent_runtime/skills/microrag-search/SKILL.md`:

````markdown
---
name: microrag-search
description: Use MicroRAG DiscoRAG retrieval evidence when answering questions about indexed local documents or when the user asks to search MicroRAG.
---

# MicroRAG Search

Retrieve local document evidence through MicroRAG's DiscoRAG mode.

## Workflow

1. Decide whether the user needs evidence from indexed MicroRAG documents.
2. Run DiscoRAG retrieval with the user's question.
3. Use stdout JSON as evidence.
4. Answer using the retrieved contexts and blueprint.
5. If retrieval fails or evidence is insufficient, say so plainly and do not invent evidence.

## Retrieve Evidence

```bash
mcrag retrieve --query "<question>" --mode discorag --top-n 6 --json
```

## Reading the Result

The command prints model-facing JSON to stdout.

Use:
- `query` as the search query context.
- `contexts` as the retrieved evidence chunks.
- `blueprint` as DiscoRAG's answer planning constraints and evidence organization.

Treat stdout JSON as evidence. stderr diagnostics are not evidence.

## Error Handling

If the command fails with `setup error:`, tell the user MicroRAG is not ready in product terms.

If retrieval returns no usable evidence, say that MicroRAG did not find enough evidence and ask the user to clarify or provide more specific terms.

Do not invent citations, document facts, or source claims.

## Common Mistakes

- Do not use stderr diagnostics as evidence.
- Do not expose runtime internals, command paths, local filesystem paths, transcript files, or process protocol details.
````

- [ ] **Step 4: Add package data entries**

Modify `pyproject.toml`:

```toml
[tool.setuptools.package-data]
ragflow_lite = [
    "static/*.css",
    "static/*.js",
    "agent_runtime/CLAUDE.md",
    "agent_runtime/settings.json",
    "agent_runtime/skills/microrag-search/SKILL.md",
]
```

- [ ] **Step 5: Commit asset scaffold**

Run:

```bash
rtk git add pyproject.toml src/ragflow_lite/agent_runtime tests/unit/agent_runtime/test_setup.py
rtk git commit -m "feat: add product agent runtime assets"
```

Expected: commit succeeds.

## Task 2: Implement Runtime Workspace Setup Helpers

Purpose: copy product runtime assets into ignored `data/agent-runtime/` and expose deterministic path/env helpers.

**Files:**
- Create: `src/ragflow_lite/agent_runtime/setup.py`
- Test: `tests/unit/agent_runtime/test_setup.py`

- [ ] **Step 1: Add failing path and env tests**

Append to `tests/unit/agent_runtime/test_setup.py`:

```python
from ragflow_lite.agent_runtime.setup import (
    build_agent_child_env,
    default_agent_runtime_paths,
    validate_agent_runtime_workspace,
)


def test_default_agent_runtime_paths_use_data_agent_runtime(tmp_path: Path) -> None:
    paths = default_agent_runtime_paths(tmp_path)

    assert paths.project_root == tmp_path
    assert paths.config_dir == tmp_path / "data" / "agent-runtime" / "config"
    assert paths.workspace_dir == tmp_path / "data" / "agent-runtime" / "workspace"


def test_setup_is_idempotent_and_overwrites_product_assets(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    skill_path = (
        paths.workspace_dir
        / ".claude"
        / "skills"
        / "microrag-search"
        / "SKILL.md"
    )
    skill_path.write_text("stale local copy", encoding="utf-8")

    setup_agent_runtime(paths)

    assert "stale local copy" not in skill_path.read_text(encoding="utf-8")
    assert "--mode discorag" in skill_path.read_text(encoding="utf-8")


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
```

- [ ] **Step 2: Run tests to verify setup helpers fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/agent_runtime/test_setup.py -q
```

Expected: FAIL with missing `ragflow_lite.agent_runtime.setup`.

- [ ] **Step 3: Implement setup helpers**

Create `src/ragflow_lite/agent_runtime/setup.py`:

```python
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


SETUP_INCOMPLETE_MESSAGE = (
    "MicroRAG agent setup is incomplete. Runtime workspace is missing."
)


@dataclass(frozen=True)
class AgentRuntimePaths:
    project_root: Path
    config_dir: Path
    workspace_dir: Path


def default_agent_runtime_paths(project_root: Path) -> AgentRuntimePaths:
    root = project_root.resolve()
    runtime_root = root / "data" / "agent-runtime"
    return AgentRuntimePaths(
        project_root=root,
        config_dir=runtime_root / "config",
        workspace_dir=runtime_root / "workspace",
    )


def setup_agent_runtime(paths: AgentRuntimePaths) -> AgentRuntimePaths:
    source_root = Path(__file__).resolve().parent
    workspace = paths.workspace_dir
    claude_dir = workspace / ".claude"
    skill_dir = claude_dir / "skills" / "microrag-search"

    paths.config_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(source_root / "CLAUDE.md", workspace / "CLAUDE.md")
    shutil.copyfile(source_root / "settings.json", claude_dir / "settings.json")
    shutil.copyfile(
        source_root / "skills" / "microrag-search" / "SKILL.md",
        skill_dir / "SKILL.md",
    )
    return paths


def validate_agent_runtime_workspace(paths: AgentRuntimePaths) -> None:
    required = (
        paths.config_dir,
        paths.workspace_dir / "CLAUDE.md",
        paths.workspace_dir / ".claude" / "settings.json",
        paths.workspace_dir
        / ".claude"
        / "skills"
        / "microrag-search"
        / "SKILL.md",
    )
    if not all(path.exists() for path in required):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)


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
    return env
```

- [ ] **Step 4: Run setup tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/agent_runtime/test_setup.py -q
```

Expected: all tests in `test_setup.py` pass.

- [ ] **Step 5: Commit setup helpers**

Run:

```bash
rtk git add src/ragflow_lite/agent_runtime tests/unit/agent_runtime/test_setup.py
rtk git commit -m "feat: add agent runtime workspace setup"
```

Expected: commit succeeds.

## Task 3: Add `mcrag agent setup`

Purpose: provide an explicit setup command that creates runtime files without requiring provider API keys or runtime services.

**Files:**
- Modify: `src/ragflow_lite/cli/mcrag.py`
- Test: `tests/unit/cli/test_mcrag_cli.py`

- [ ] **Step 1: Write failing CLI setup tests**

Append to `tests/unit/cli/test_mcrag_cli.py`:

```python
def test_agent_setup_command_writes_runtime_workspace(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    exit_code = main(["agent", "setup", "--project-root", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload == {
        "config_dir": str(tmp_path / "data" / "agent-runtime" / "config"),
        "workspace_dir": str(tmp_path / "data" / "agent-runtime" / "workspace"),
    }
    assert (tmp_path / "data" / "agent-runtime" / "workspace" / "CLAUDE.md").exists()


def test_agent_setup_does_not_build_runtime_services(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    def failing_factory() -> AppServices:
        raise AssertionError("setup must not build AppServices")

    exit_code = main(
        ["agent", "setup", "--project-root", str(tmp_path)],
        services_factory=failing_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/cli/test_mcrag_cli.py::test_agent_setup_command_writes_runtime_workspace tests/unit/cli/test_mcrag_cli.py::test_agent_setup_does_not_build_runtime_services -q
```

Expected: FAIL because `agent` is not a registered command.

- [ ] **Step 3: Add setup command parsing and handler**

Modify `src/ragflow_lite/cli/mcrag.py`:

```python
def _build_parser() -> ExitCodeParser:
    parser = ExitCodeParser(prog="mcrag")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("retrieve", "answer"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--query", required=True)
        subparser.add_argument(
            "--mode",
            choices=("standard", "discorag"),
            default="standard",
        )
        subparser.add_argument("--top-n", type=int, default=6)
        subparser.add_argument(
            "--json",
            action="store_true",
            help="输出 machine-readable JSON。",
        )

    agent_parser = subparsers.add_parser("agent")
    agent_subparsers = agent_parser.add_subparsers(
        dest="agent_command",
        required=True,
    )
    setup_parser = agent_subparsers.add_parser("setup")
    setup_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="MicroRAG project root used to generate data/agent-runtime.",
    )

    return parser
```

Add a handler:

```python
def _handle_agent_setup(args: argparse.Namespace) -> int:
    from ragflow_lite.agent_runtime.setup import (
        default_agent_runtime_paths,
        setup_agent_runtime,
    )

    paths = setup_agent_runtime(default_agent_runtime_paths(args.project_root))
    _write_json(
        {
            "config_dir": str(paths.config_dir),
            "workspace_dir": str(paths.workspace_dir),
        }
    )
    return 0
```

Change `main()` so setup returns before `_require_json_flag()` and before service construction:

```python
def main(
    argv: Sequence[str] | None = None,
    services_factory: Callable[[], "AppServices"] | None = None,
) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        if args.command == "agent" and args.agent_command == "setup":
            return _handle_agent_setup(args)
        _require_json_flag(args, parser)
    except CliArgumentError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    factory = services_factory or _default_services_factory
    try:
        services = factory()
    except Exception as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.command == "retrieve":
            return _handle_retrieve(args, services)
        if args.command == "answer":
            return _handle_answer(args, services)
        raise RuntimeError(f"Unsupported command: {args.command}")
    except Exception as exc:
        if _is_ragflow_lite_error(exc):
            print(f"MicroRAG error: {exc}", file=sys.stderr)
            return 1
        print(f"Runtime error: {exc}", file=sys.stderr)
        return 1
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/cli/test_mcrag_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit CLI setup**

Run:

```bash
rtk git add src/ragflow_lite/cli/mcrag.py tests/unit/cli/test_mcrag_cli.py
rtk git commit -m "feat: add mcrag agent setup"
```

Expected: commit succeeds.

## Task 4: Add ACP Child Environment Support

Purpose: make `CLAUDE_CONFIG_DIR`, `PATH`, and `PYTHONPATH` real child process inputs, not documentation-only values.

**Files:**
- Modify: `src/ragflow_lite/infrastructure/agent/acp_client.py`
- Test: `tests/unit/infrastructure/test_acp_client_redaction.py`

- [ ] **Step 1: Write failing env injection test**

Append to `tests/unit/infrastructure/test_acp_client_redaction.py`:

```python
def test_start_passes_configured_child_env() -> None:
    from ragflow_lite.infrastructure.agent.acp_client import (
        AcpClient,
        AcpRuntimeConfig,
    )

    calls: list[tuple[str, list[str], str, dict[str, str]]] = []

    def process_factory(
        command: str,
        args: list[str],
        cwd: str,
        env: dict[str, str],
    ):
        calls.append((command, args, cwd, env))
        raise FileNotFoundError("missing executable")

    client = AcpClient(
        config=AcpRuntimeConfig(
            command="agent",
            args=["--acp"],
            cwd="/runtime/workspace",
            env={"CLAUDE_CONFIG_DIR": "/runtime/config"},
        ),
        process_factory=process_factory,
    )

    with pytest.raises(RuntimeError):
        client.start()

    assert calls == [
        (
            "agent",
            ["--acp"],
            "/runtime/workspace",
            {"CLAUDE_CONFIG_DIR": "/runtime/config"},
        )
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_acp_client_redaction.py::test_start_passes_configured_child_env -q
```

Expected: FAIL because `AcpRuntimeConfig` does not accept `env`.

- [ ] **Step 3: Implement env support**

Modify `src/ragflow_lite/infrastructure/agent/acp_client.py`:

```python
import os
```

Change `AcpRuntimeConfig`:

```python
@dataclass(frozen=True)
class AcpRuntimeConfig:
    command: str
    args: list[str]
    cwd: str
    env: dict[str, str] = field(default_factory=dict)
```

Change `_default_process_factory`:

```python
def _default_process_factory(
    command: str,
    args: list[str],
    cwd: str,
    env: Mapping[str, str] | None = None,
) -> subprocess.Popen[str]:
    child_env = os.environ.copy()
    if env is not None:
        child_env.update(env)
    return subprocess.Popen(
        [command, *args],
        cwd=cwd,
        env=child_env,
        stdin=PIPE,
        stdout=PIPE,
        stderr=PIPE,
        text=True,
    )
```

Change `AcpClient.start()` process factory call:

```python
self._process = self._process_factory(
    self._config.command,
    self._config.args,
    self._config.cwd,
    self._config.env,
)
```

- [ ] **Step 4: Run ACP redaction/env tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_acp_client_redaction.py -q
```

Expected: all tests pass, including existing traceback redaction tests.

- [ ] **Step 5: Commit ACP env support**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure/agent/acp_client.py tests/unit/infrastructure/test_acp_client_redaction.py
rtk git commit -m "feat: pass isolated env to agent runtime"
```

Expected: commit succeeds.

## Task 5: Add Runtime Defaults to Settings

Purpose: make default runtime config point to `data/agent-runtime/` instead of requiring callers to set `MICRORAG_AGENT_CWD`.

**Files:**
- Modify: `src/ragflow_lite/config/settings.py`
- Test: `tests/unit/api/test_acp_wiring.py`

- [ ] **Step 1: Write failing settings default test**

Append to `tests/unit/api/test_acp_wiring.py`:

```python
def test_settings_default_agent_runtime_paths() -> None:
    settings = Settings.default(Path("/tmp/test-project"))

    assert settings.agent_cwd == str(
        Path("/tmp/test-project") / "data" / "agent-runtime" / "workspace"
    )
    assert settings.agent_config_dir == str(
        Path("/tmp/test-project") / "data" / "agent-runtime" / "config"
    )
    assert settings.agent_args == "--acp --setting-sources project,local"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_acp_wiring.py::test_settings_default_agent_runtime_paths -q
```

Expected: FAIL because `Settings` does not have `agent_config_dir` and defaults `agent_cwd` to `None`.

- [ ] **Step 3: Add settings fields and defaults**

Modify `Settings` in `src/ragflow_lite/config/settings.py`:

```python
agent_args: str = field(
    default_factory=lambda: _read_string_env(
        "MICRORAG_AGENT_ARGS",
        "--acp --setting-sources project,local",
    )
)
agent_cwd: str | None = field(
    default_factory=lambda: _read_optional_env("MICRORAG_AGENT_CWD")
)
agent_config_dir: str | None = field(
    default_factory=lambda: (
        _read_optional_env("MICRORAG_AGENT_CONFIG_DIR")
        or _read_optional_env("CLAUDE_CONFIG_DIR")
    )
)
```

Change `Settings.default()` to derive default runtime paths:

```python
@classmethod
def default(cls, project_root: Path | None = None) -> "Settings":
    root = project_root or Path(__file__).resolve().parents[3]
    runtime_root = root / "data" / "agent-runtime"
    return cls(
        project_root=root,
        uploads_dir=root / "data" / "uploads",
        local_index_dir=root / "data" / "local_index",
        temp_dir=root / "data" / "tmp",
        agent_cwd=(
            _read_optional_env("MICRORAG_AGENT_CWD")
            or str(runtime_root / "workspace")
        ),
        agent_config_dir=(
            _read_optional_env("MICRORAG_AGENT_CONFIG_DIR")
            or _read_optional_env("CLAUDE_CONFIG_DIR")
            or str(runtime_root / "config")
        ),
    )
```

Do not add agent runtime directories to `ensure_directories()`. Runtime setup stays explicit through `mcrag agent setup`.

- [ ] **Step 4: Run settings/wiring test**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_acp_wiring.py::test_settings_default_agent_runtime_paths -q
```

Expected: PASS.

- [ ] **Step 5: Commit settings defaults**

Run:

```bash
rtk git add src/ragflow_lite/config/settings.py tests/unit/api/test_acp_wiring.py
rtk git commit -m "feat: default agent runtime to isolated workspace"
```

Expected: commit succeeds.

## Task 6: Wire ACP to Isolated Runtime Paths

Purpose: make `build_services()` start ACP with isolated cwd and `CLAUDE_CONFIG_DIR`, and fail clearly when setup has not run.

**Files:**
- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/api/test_acp_wiring.py`

- [ ] **Step 1: Replace stale fallback test with isolation tests**

In `tests/unit/api/test_acp_wiring.py`, replace `test_falls_back_to_project_root_when_cwd_not_set` with:

```python
def test_requires_agent_runtime_workspace_when_cwd_missing(self) -> None:
    settings = self._make_settings(agent_cwd=None)

    try:
        _build_acp_client(settings)
    except RuntimeError as exc:
        assert str(exc) == (
            "MicroRAG agent setup is incomplete. Runtime workspace is missing."
        )
    else:
        raise AssertionError("_build_acp_client should require runtime setup")
```

Append:

```python
def test_build_acp_client_sets_isolated_runtime_env(tmp_path: Path) -> None:
    from ragflow_lite.agent_runtime.setup import (
        default_agent_runtime_paths,
        setup_agent_runtime,
    )

    paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_acp_wiring.py -q
```

Expected: FAIL because `_build_acp_client()` still falls back to project root and does not set env.

- [ ] **Step 3: Implement isolated ACP wiring**

Modify `_build_acp_client()` in `src/ragflow_lite/api/deps/providers.py`:

```python
def _build_acp_client(settings: Settings) -> AcpClient:
    from ragflow_lite.agent_runtime.setup import (
        AgentRuntimePaths,
        build_agent_child_env,
        validate_agent_runtime_workspace,
    )

    if settings.agent_cwd is None or settings.agent_config_dir is None:
        raise RuntimeError(
            "MicroRAG agent setup is incomplete. Runtime workspace is missing."
        )

    paths = AgentRuntimePaths(
        project_root=settings.project_root,
        config_dir=Path(settings.agent_config_dir),
        workspace_dir=Path(settings.agent_cwd),
    )
    validate_agent_runtime_workspace(paths)
    config = AcpRuntimeConfig(
        command=settings.agent_command,
        args=settings.agent_args.split(),
        cwd=str(paths.workspace_dir),
        env=build_agent_child_env(paths),
    )
    return AcpClient(config=config)
```

Add `from pathlib import Path` near the top of `providers.py` if the file does not already import it.

- [ ] **Step 4: Run wiring tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_acp_wiring.py -q
```

Expected: all ACP wiring tests pass.

- [ ] **Step 5: Commit ACP isolated wiring**

Run:

```bash
rtk git add src/ragflow_lite/api/deps/providers.py tests/unit/api/test_acp_wiring.py
rtk git commit -m "feat: wire acp to isolated agent workspace"
```

Expected: commit succeeds.

## Task 7: Align Development Skill Copy

Purpose: keep the existing repository-root development skill from contradicting the product runtime skill while making clear that product runtime uses generated workspace assets.

**Files:**
- Modify: `.claude/skills/microrag-search/SKILL.md`
- Test: `tests/unit/agent_runtime/test_setup.py`

- [ ] **Step 1: Add a source skill parity test**

Append to `tests/unit/agent_runtime/test_setup.py`:

```python
def test_repository_skill_matches_product_discorag_contract() -> None:
    repo_skill = Path(".claude/skills/microrag-search/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "## Workflow" in repo_skill
    assert "mcrag retrieve" in repo_skill
    assert "--mode discorag" in repo_skill
    assert "--mode standard" not in repo_skill
    assert "mcrag answer" not in repo_skill
```

- [ ] **Step 2: Run parity test to verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/unit/agent_runtime/test_setup.py::test_repository_skill_matches_product_discorag_contract -q
```

Expected: FAIL because the repository skill still contains standard and answer guidance.

- [ ] **Step 3: Replace repository skill with the same product-facing contract**

Set `.claude/skills/microrag-search/SKILL.md` to:

````markdown
---
name: microrag-search
description: Use MicroRAG DiscoRAG retrieval evidence when answering questions about indexed local documents or when the user asks to search MicroRAG.
---

# MicroRAG Search

Retrieve local document evidence through MicroRAG's DiscoRAG mode.

## Workflow

1. Decide whether the user needs evidence from indexed MicroRAG documents.
2. Run DiscoRAG retrieval with the user's question.
3. Use stdout JSON as evidence.
4. Answer using the retrieved contexts and blueprint.
5. If retrieval fails or evidence is insufficient, say so plainly and do not invent evidence.

## Retrieve Evidence

```bash
mcrag retrieve --query "<question>" --mode discorag --top-n 6 --json
```

## Reading the Result

The command prints model-facing JSON to stdout.

Use:
- `query` as the search query context.
- `contexts` as the retrieved evidence chunks.
- `blueprint` as DiscoRAG's answer planning constraints and evidence organization.

Treat stdout JSON as evidence. stderr diagnostics are not evidence.

## Error Handling

If the command fails with `setup error:`, tell the user MicroRAG is not ready in product terms.

If retrieval returns no usable evidence, say that MicroRAG did not find enough evidence and ask the user to clarify or provide more specific terms.

Do not invent citations, document facts, or source claims.

## Common Mistakes

- Do not use stderr diagnostics as evidence.
- Do not expose runtime internals, command paths, local filesystem paths, transcript files, or process protocol details.
````

- [ ] **Step 4: Run skill tests**

Run:

```bash
.venv/bin/python -m pytest tests/unit/agent_runtime/test_setup.py -q
```

Expected: all setup/skill tests pass.

- [ ] **Step 5: Commit skill alignment**

Run:

```bash
rtk git add .claude/skills/microrag-search/SKILL.md tests/unit/agent_runtime/test_setup.py
rtk git commit -m "docs: align microrag search skill with discorag runtime"
```

Expected: commit succeeds.

## Task 8: Update Infrastructure Contract

Purpose: make the active module contract match the new runtime isolation behavior after source-backed changes land.

**Files:**
- Modify: `src/ragflow_lite/infrastructure/CONTRACTS.md`

- [ ] **Step 1: Edit ACP runtime contract**

In `src/ragflow_lite/infrastructure/CONTRACTS.md`, update the `ACP Runtime and Session Store Contract` block.

Replace the stale settings bullet:

```markdown
- `AcpClient` is wired into `AppServices` via `_build_acp_client(settings)` in `build_services()`. Settings fields: `agent_command` (env `MICRORAG_AGENT_COMMAND`, default `"claude"`), `agent_args` (env `MICRORAG_AGENT_ARGS`, default `"--acp"`), `agent_cwd` (env `MICRORAG_AGENT_CWD`, falls back to `project_root`).
```

With:

```markdown
- `AcpClient` is wired into `AppServices` via `_build_acp_client(settings)` in `build_services()`. Settings fields: `agent_command` (env `MICRORAG_AGENT_COMMAND`, default `"claude"`), `agent_args` (env `MICRORAG_AGENT_ARGS`, default `"--acp --setting-sources project,local"`), `agent_cwd` (env `MICRORAG_AGENT_CWD`, default `data/agent-runtime/workspace`), and `agent_config_dir` (env `MICRORAG_AGENT_CONFIG_DIR` or `CLAUDE_CONFIG_DIR`, default `data/agent-runtime/config`).
- Product agent runtime files are generated from `src/ragflow_lite/agent_runtime/` by `mcrag agent setup`. `data/agent-runtime/` is runtime state and is not the source of truth.
- ACP child processes receive `CLAUDE_CONFIG_DIR`, `PATH`, and `PYTHONPATH` through `AcpRuntimeConfig.env`.
```

Add forbidden stale interpretations:

```markdown
- Do not fall back to repository root as product ACP cwd.
- Do not treat repository-root `.claude/settings*` or real `~/.claude/settings.json` as product runtime configuration.
- Do not expose `mcrag answer` through the product `microrag-search` skill.
```

Add verification links:

```markdown
- [tests/unit/agent_runtime/test_setup.py](../../../tests/unit/agent_runtime/test_setup.py)
```

- [ ] **Step 2: Scan contract for stale project-root fallback**

Run:

```bash
rg -n "falls back to `project_root`|fallback to project_root|repository root as product ACP cwd|mcrag answer.*product" src/ragflow_lite/infrastructure/CONTRACTS.md
```

Expected: no stale project-root fallback remains; only forbidden stale interpretation text may mention repository root.

- [ ] **Step 3: Commit contract update**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure/CONTRACTS.md
rtk git commit -m "docs: update agent runtime isolation contract"
```

Expected: commit succeeds.

## Task 9: Focused Verification

Purpose: verify runtime isolation behavior before running the full suite.

**Files:**
- Verify: `src/ragflow_lite/agent_runtime/**`
- Verify: `src/ragflow_lite/cli/mcrag.py`
- Verify: `src/ragflow_lite/api/deps/providers.py`
- Verify: `src/ragflow_lite/infrastructure/agent/acp_client.py`

- [ ] **Step 1: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/agent_runtime/test_setup.py \
  tests/unit/cli/test_mcrag_cli.py \
  tests/unit/api/test_acp_wiring.py \
  tests/unit/infrastructure/test_acp_client_redaction.py \
  tests/integration/api/test_ui_shell.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run setup command manually**

Run:

```bash
.venv/bin/python -m ragflow_lite.cli.mcrag agent setup --project-root /home/xia/ragflow-lite
```

Expected stdout is JSON:

```json
{
  "config_dir": "/home/xia/ragflow-lite/data/agent-runtime/config",
  "workspace_dir": "/home/xia/ragflow-lite/data/agent-runtime/workspace"
}
```

- [ ] **Step 3: Inspect generated files**

Run:

```bash
rtk test -f data/agent-runtime/workspace/CLAUDE.md
rtk test -f data/agent-runtime/workspace/.claude/settings.json
rtk test -f data/agent-runtime/workspace/.claude/skills/microrag-search/SKILL.md
```

Expected: all commands exit with code `0`.

- [ ] **Step 4: Scan generated product assets**

Run:

```bash
rg -n "AGENTS.md|CONTRACTS.md|cx |pytest|git workflow|code-review|Claude Code|--mode standard|mcrag answer" data/agent-runtime/workspace
```

Expected: no matches.

- [ ] **Step 5: Scan UI/static visible strings**

Run:

```bash
rg -n "Claude Code|claude-code|transcript_path|MICRORAG_AGENT_CWD|CLAUDE_CONFIG_DIR" src/ragflow_lite/static src/ragflow_lite/api/routes
```

Expected: no UI-visible leak matches. Server-side implementation names in non-UI code are out of scope for this scan.

## Task 10: Full Verification and Runtime Smoke

Purpose: confirm the implementation did not regress existing MicroRAG behavior and the demo can be started with the generated runtime workspace.

**Files:**
- Verify: entire repository

- [ ] **Step 1: Run full tests**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: existing suite passes. If skipped tests exist, report the skip count exactly.

- [ ] **Step 2: Run ruff**

Run:

```bash
.venv/bin/python -m ruff check .
```

Expected: no new ruff errors from this change. If pre-existing ruff errors remain, list the count and confirm changed files are clean.

- [ ] **Step 3: Start backend after setup**

Run:

```bash
.venv/bin/python -m uvicorn ragflow_lite.app:app --host 127.0.0.1 --port 8001 --reload
```

Expected:

```text
Application startup complete.
```

Provider env vars must already be exported before this command:

```bash
export DEEPSEEK_API_KEY="..."
export ARK_API_KEY="..."
export ARK_EMBEDDING_MODEL="..."
```

- [ ] **Step 4: Verify web shell loads**

Run in another shell:

```bash
curl -s -o /tmp/microrag-agent.html -w "%{http_code}\n" http://127.0.0.1:8001/agent
```

Expected:

```text
200
```

- [ ] **Step 5: Manual runtime settings-source verification**

Run:

```bash
cd /home/xia/ragflow-lite/data/agent-runtime/workspace
CLAUDE_CONFIG_DIR=/home/xia/ragflow-lite/data/agent-runtime/config \
PATH=/home/xia/ragflow-lite/.venv/bin:$PATH \
PYTHONPATH=/home/xia/ragflow-lite/src \
claude --setting-sources project,local
```

Then type:

```text
/status
```

Expected: settings sources include `data/agent-runtime/workspace/.claude/settings.json` and do not include `/home/xia/ragflow-lite/.claude/settings.json` or real `~/.claude/settings.json`.

- [ ] **Step 6: Commit final verification notes if docs changed**

If implementation changed no additional docs after Task 8, skip this commit. If verification exposed a contract wording correction, commit it:

```bash
rtk git add src/ragflow_lite/infrastructure/CONTRACTS.md
rtk git commit -m "docs: clarify agent runtime verification"
```

Expected: commit only if `CONTRACTS.md` changed.

## Self-Review

- Spec coverage:
  - Dedicated runtime workspace: Tasks 1, 2, 3, 5, 6.
  - `CLAUDE_CONFIG_DIR`: Tasks 2, 4, 5, 6, 10.
  - Product-only `CLAUDE.md`, `settings.json`, skill: Tasks 1, 2, 7.
  - DiscoRAG-only skill and no `mcrag answer`: Tasks 1, 7, 9.
  - Clear setup failure: Tasks 2 and 6.
  - Manual `/status` verification: Task 10.
  - Active contract update after code lands: Task 8.
- Placeholder scan: no `TBD`, `TODO`, or unfilled task steps.
- Type consistency:
  - `AgentRuntimePaths` fields are `project_root`, `config_dir`, `workspace_dir` in every task.
  - `AcpRuntimeConfig.env` is a `dict[str, str]` in tests and implementation snippets.
  - Settings field is consistently named `agent_config_dir`.
