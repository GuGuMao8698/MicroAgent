# MicroRAG Agent Runtime Isolation Review Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the runtime isolation review blockers so non-agent MicroRAG paths keep working without agent setup while product agent runtime paths remain strictly isolated.

**Architecture:** Keep `AppServices` as the service container but make ACP client construction lazy so `build_services()`, `/api/v0/queries`, `mcrag retrieve`, and `mcrag answer` do not require `data/agent-runtime/`. Tighten runtime path validation so ACP can only use the project-owned `data/agent-runtime/config` and `data/agent-runtime/workspace`, then apply small drift-prevention simplifications around setup messages and repeated test setup.

**Tech Stack:** Python 3.13, FastAPI, stdlib `dataclasses`, stdlib `pathlib`, stdlib `argparse`, pytest, existing MicroRAG `Settings`, `AppServices`, `AcpClient`, `AgentRuntimePaths`, and `mcrag` CLI.

---

Date: 2026-05-15
Status: Ready for implementation after confirmation
Fixes review findings from commits `375d4b1..d88d940`.
Related plan:
[2026-05-15-microrag-agent-runtime-workspace-isolation.md](2026-05-15-microrag-agent-runtime-workspace-isolation.md)

## File Structure

Files to modify:

- `src/ragflow_lite/agent_runtime/setup.py`
  - Add strict default-path validation helper and reuse the centralized setup error message.
- `src/ragflow_lite/api/deps/providers.py`
  - Convert `AppServices.acp_client` to lazy construction so non-agent service graph creation does not validate or require agent runtime setup.
- `src/ragflow_lite/config/settings.py`
  - Stop accepting ambient `CLAUDE_CONFIG_DIR` as a product runtime default. Keep product config path owned by `MICRORAG_AGENT_CONFIG_DIR` or the default `data/agent-runtime/config`.
- `src/ragflow_lite/cli/mcrag.py`
  - Normalize CLI setup error marker casing.
- `src/ragflow_lite/agent_runtime/skills/microrag-search/SKILL.md`
  - Make setup-error guidance case-insensitive instead of quoting a mismatched literal.
- `.claude/skills/microrag-search/SKILL.md`
  - Mirror the product skill setup-error wording.
- `src/ragflow_lite/infrastructure/CONTRACTS.md`
  - Update active contract for lazy ACP construction and strict product-owned paths.
- `tests/conftest.py`
  - Add a small shared helper for test runtime setup.
- `tests/unit/api/test_acp_wiring.py`
  - Cover lazy construction, strict path validation, and env override rejection.
- `tests/unit/api/test_providers.py`
  - Cover `build_services()` without agent runtime setup.
- `tests/unit/cli/test_mcrag_cli.py`
  - Cover unchanged `mcrag retrieve` / `mcrag answer` service-factory behavior and normalized setup error marker.
- `tests/unit/agent_runtime/test_setup.py`
  - Cover strict default path validation and rejected arbitrary paths.
- `tests/unit/api/test_agent_routes.py`
  - Cover that agent routes surface product setup errors when lazy ACP construction fails.
- `tests/integration/api/test_ui_shell.py`
  - Use shared helper only if needed after test fixture simplification.

## Implementation Notes

- Do not roll back runtime workspace assets, `mcrag agent setup`, or child env injection.
- Preserve `mcrag retrieve` and `mcrag answer` behavior. Product skill remains DiscoRAG-only, but CLI remains dual-use.
- Non-agent paths must not call `validate_agent_runtime_workspace()`.
- Agent paths must call validation before starting ACP.
- Runtime isolation must reject repo root, repo-root `.claude`, real `~/.claude`, and arbitrary alternate workspaces even if expected files exist.
- Keep override semantics narrow:
  - `MICRORAG_AGENT_COMMAND` and `MICRORAG_AGENT_ARGS` remain operator overrides.
  - `MICRORAG_AGENT_CWD` and `MICRORAG_AGENT_CONFIG_DIR` may remain fields for tests or future packaging, but `_build_acp_client()` must reject values that do not resolve to the default product-owned paths for `settings.project_root`.
  - Do not use bare `CLAUDE_CONFIG_DIR` to choose product runtime config.
- Avoid broad refactors. Fix the two blocking review findings and the concrete simplifications only.

## Task 0: Baseline Review Reproduction

Purpose: confirm the two blocking review findings are present before fixing.

**Files:**
- Read: `src/ragflow_lite/api/deps/providers.py`
- Read: `src/ragflow_lite/agent_runtime/setup.py`
- Read: `src/ragflow_lite/config/settings.py`
- Read: `tests/unit/api/test_acp_wiring.py`

- [ ] **Step 1: Confirm current branch state**

Run:

```bash
rtk git status --short --branch
```

Expected:

```text
## main...origin/main [ahead 10]
```

- [ ] **Step 2: Confirm eager ACP construction**

Run:

```bash
cx definition --name build_services --from src/ragflow_lite/api/deps/providers.py | sed -n '1,40p'
```

Expected current output contains:

```python
acp_client = _build_acp_client(settings)
```

- [ ] **Step 3: Confirm path validation is only file-existence validation**

Run:

```bash
cx definition --name validate_agent_runtime_workspace --from src/ragflow_lite/agent_runtime/setup.py
```

Expected current output contains:

```python
if not all(path.exists() for path in required):
    raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
```

## Task 1: Make ACP Client Lazy in AppServices

Purpose: remove the regression where non-agent service creation requires `mcrag agent setup`.

**Files:**
- Modify: `src/ragflow_lite/api/deps/providers.py`
- Test: `tests/unit/api/test_acp_wiring.py`
- Test: `tests/unit/api/test_providers.py`

- [ ] **Step 1: Write failing lazy construction tests**

Append to `tests/unit/api/test_acp_wiring.py`:

```python
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
```

Add imports at the top of `tests/unit/api/test_acp_wiring.py`:

```python
from ragflow_lite.api.deps.providers import AppServices, _build_acp_client
```

Append to `tests/unit/api/test_providers.py`:

```python
def test_build_services_does_not_require_agent_runtime_setup(tmp_path: Path) -> None:
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
        deepseek_api_key="test-key",
        ark_api_key="test-ark-key",
        ark_embedding_model="test-model",
        infinity_database="test_db",
        infinity_document_table=f"documents_{uuid4().hex[:8]}",
        infinity_chunk_table=f"chunks_{uuid4().hex[:8]}",
        infinity_graph_entity_table=f"graph_entities_{uuid4().hex[:8]}",
        infinity_graph_relationship_table=f"graph_relationships_{uuid4().hex[:8]}",
    )
    settings.ensure_directories()

    services = build_services(settings)

    assert services.settings is settings
```

Ensure `tests/unit/api/test_providers.py` already imports `uuid4`, `Settings`, and `build_services`. If not, add:

```python
from uuid import uuid4

from ragflow_lite.api.deps.providers import build_services
from ragflow_lite.config import Settings
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/api/test_acp_wiring.py::test_app_services_acp_client_is_lazy \
  tests/unit/api/test_providers.py::test_build_services_does_not_require_agent_runtime_setup \
  -q
```

Expected: FAIL because `AppServices` does not accept `acp_client_factory` and `build_services()` still calls `_build_acp_client()` eagerly.

- [ ] **Step 3: Implement lazy ACP construction**

Modify `src/ragflow_lite/api/deps/providers.py`.

Add import:

```python
from collections.abc import Callable
```

Change `AppServices`:

```python
@dataclass(slots=True)
class AppServices:
    """集中保存应用启动后可复用的核心服务对象。"""

    settings: Settings
    agent_session_store: AgentSessionStore
    acp_client_factory: Callable[[], AcpClient]
    ingestion_pipeline: IngestionPipeline
    retriever: Retriever
    query_service: QueryService
    discorag_query_service: DiscoRAGQueryService
    query_router: QueryModeRouter
    document_service: DocumentService
    dataset_service: DatasetService
    task_store: IngestionTaskStore = field(default_factory=InMemoryTaskStore)
    stage_cache: IngestionStageCache = field(default_factory=InMemoryStageCache)
    structurer_config: DiscoRAGStructurerRuntimeConfig | None = None
    _acp_client: AcpClient | None = field(default=None, init=False, repr=False)

    @property
    def acp_client(self) -> AcpClient:
        if self._acp_client is None:
            self._acp_client = self.acp_client_factory()
        return self._acp_client
```

Change `build_services()`:

```python
    agent_session_store = AgentSessionStore(
        settings.local_index_dir / "agent_sessions.sqlite3"
    )
```

Delete:

```python
    acp_client = _build_acp_client(settings)
```

Change the return block:

```python
        agent_session_store=agent_session_store,
        acp_client_factory=lambda: _build_acp_client(settings),
        ingestion_pipeline=pipeline,
```

- [ ] **Step 4: Update tests that instantiate AppServices directly**

Search:

```bash
rg -n "AppServices\\(" tests src
```

For tests that pass `acp_client=...`, replace with a factory:

```python
acp_client_factory=lambda: fake_acp_client
```

Do not modify route-level `_FakeServices` in `tests/unit/api/test_agent_routes.py`; those tests intentionally use a lightweight fake with an `acp_client` attribute.

- [ ] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/api/test_acp_wiring.py \
  tests/unit/api/test_providers.py \
  tests/unit/cli/test_mcrag_cli.py \
  tests/integration/api/test_ui_shell.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit lazy ACP fix**

Run:

```bash
rtk git add src/ragflow_lite/api/deps/providers.py tests/unit/api/test_acp_wiring.py tests/unit/api/test_providers.py tests/unit/cli/test_mcrag_cli.py tests/integration/api/test_ui_shell.py
rtk git commit -m "fix: defer agent runtime setup to agent usage"
```

Expected: commit succeeds.

## Task 2: Enforce Product-Owned Runtime Paths

Purpose: close the bypass where env overrides can redirect product agent runtime to repo root, real home config, or arbitrary matching files.

**Files:**
- Modify: `src/ragflow_lite/agent_runtime/setup.py`
- Modify: `src/ragflow_lite/api/deps/providers.py`
- Modify: `src/ragflow_lite/config/settings.py`
- Test: `tests/unit/agent_runtime/test_setup.py`
- Test: `tests/unit/api/test_acp_wiring.py`

- [ ] **Step 1: Write failing strict path tests**

Append to `tests/unit/agent_runtime/test_setup.py`:

```python
from ragflow_lite.agent_runtime.setup import validate_agent_runtime_paths


def test_validate_agent_runtime_paths_accepts_default_paths(tmp_path: Path) -> None:
    paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))

    validate_agent_runtime_paths(paths)


def test_validate_agent_runtime_paths_rejects_repo_root_workspace(
    tmp_path: Path,
) -> None:
    default_paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
    repo_root_paths = AgentRuntimePaths(
        project_root=tmp_path,
        config_dir=default_paths.config_dir,
        workspace_dir=tmp_path,
    )

    try:
        validate_agent_runtime_paths(repo_root_paths)
    except RuntimeError as exc:
        assert str(exc) == (
            "MicroRAG agent setup is incomplete. Runtime workspace is missing."
        )
    else:
        raise AssertionError("repo root workspace must be rejected")


def test_validate_agent_runtime_paths_rejects_home_config_dir(
    tmp_path: Path,
) -> None:
    paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
    home_config_paths = AgentRuntimePaths(
        project_root=tmp_path,
        config_dir=Path.home() / ".claude",
        workspace_dir=paths.workspace_dir,
    )

    try:
        validate_agent_runtime_paths(home_config_paths)
    except RuntimeError as exc:
        assert str(exc) == (
            "MicroRAG agent setup is incomplete. Runtime workspace is missing."
        )
    else:
        raise AssertionError("home config dir must be rejected")
```

Append to `tests/unit/api/test_acp_wiring.py`:

```python
def test_build_acp_client_rejects_non_default_runtime_paths(tmp_path: Path) -> None:
    default_paths = setup_agent_runtime(default_agent_runtime_paths(tmp_path))
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
```

Add imports:

```python
from ragflow_lite.agent_runtime.setup import (
    SETUP_INCOMPLETE_MESSAGE,
    AgentRuntimePaths,
    default_agent_runtime_paths,
    setup_agent_runtime,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/agent_runtime/test_setup.py::test_validate_agent_runtime_paths_accepts_default_paths \
  tests/unit/agent_runtime/test_setup.py::test_validate_agent_runtime_paths_rejects_repo_root_workspace \
  tests/unit/agent_runtime/test_setup.py::test_validate_agent_runtime_paths_rejects_home_config_dir \
  tests/unit/api/test_acp_wiring.py::test_build_acp_client_rejects_non_default_runtime_paths \
  -q
```

Expected: FAIL because `validate_agent_runtime_paths` does not exist and `_build_acp_client()` accepts arbitrary existing runtime paths.

- [ ] **Step 3: Implement strict path validation**

Modify `src/ragflow_lite/agent_runtime/setup.py`:

```python
def _same_path(left: Path, right: Path) -> bool:
    return left.expanduser().resolve() == right.expanduser().resolve()


def validate_agent_runtime_paths(paths: AgentRuntimePaths) -> None:
    expected = default_agent_runtime_paths(paths.project_root)
    if not _same_path(paths.config_dir, expected.config_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
    if not _same_path(paths.workspace_dir, expected.workspace_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)


def validate_agent_runtime_workspace(paths: AgentRuntimePaths) -> None:
    validate_agent_runtime_paths(paths)
    required = (
        paths.config_dir,
        paths.workspace_dir / "CLAUDE.md",
        paths.workspace_dir / ".claude" / "settings.json",
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md",
    )
    if not all(path.exists() for path in required):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
```

Export it in `src/ragflow_lite/agent_runtime/__init__.py`:

```python
from ragflow_lite.agent_runtime.setup import (
    AgentRuntimePaths,
    default_agent_runtime_paths,
    setup_agent_runtime,
    validate_agent_runtime_paths,
)

__all__ = [
    "AgentRuntimePaths",
    "default_agent_runtime_paths",
    "setup_agent_runtime",
    "validate_agent_runtime_paths",
]
```

- [ ] **Step 4: Stop accepting bare `CLAUDE_CONFIG_DIR` as a settings source**

Modify `src/ragflow_lite/config/settings.py`.

Change field default:

```python
agent_config_dir: str | None = field(
    default_factory=lambda: _read_optional_env("MICRORAG_AGENT_CONFIG_DIR")
)
```

Change `Settings.default()`:

```python
agent_config_dir=(
    _read_optional_env("MICRORAG_AGENT_CONFIG_DIR")
    or str(runtime_root / "config")
),
```

This does not prevent `build_agent_child_env()` from setting `CLAUDE_CONFIG_DIR` for the child process. It only prevents ambient parent shell `CLAUDE_CONFIG_DIR` from choosing product runtime config.

- [ ] **Step 5: Reuse centralized setup message in provider**

Modify `_build_acp_client()` imports in `src/ragflow_lite/api/deps/providers.py`:

```python
from ragflow_lite.agent_runtime.setup import (
    SETUP_INCOMPLETE_MESSAGE,
    AgentRuntimePaths,
    build_agent_child_env,
    validate_agent_runtime_workspace,
)
```

Change the missing-path branch:

```python
if settings.agent_cwd is None or settings.agent_config_dir is None:
    raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
```

- [ ] **Step 6: Run strict path tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/agent_runtime/test_setup.py \
  tests/unit/api/test_acp_wiring.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit strict isolation fix**

Run:

```bash
rtk git add src/ragflow_lite/agent_runtime src/ragflow_lite/api/deps/providers.py src/ragflow_lite/config/settings.py tests/unit/agent_runtime/test_setup.py tests/unit/api/test_acp_wiring.py
rtk git commit -m "fix: enforce product-owned agent runtime paths"
```

Expected: commit succeeds.

## Task 3: Normalize Setup Error Guidance

Purpose: remove the case mismatch between CLI stderr and product skill instructions.

**Files:**
- Modify: `src/ragflow_lite/cli/mcrag.py`
- Modify: `src/ragflow_lite/agent_runtime/skills/microrag-search/SKILL.md`
- Modify: `.claude/skills/microrag-search/SKILL.md`
- Test: `tests/unit/cli/test_mcrag_cli.py`
- Test: `tests/unit/agent_runtime/test_setup.py`

- [ ] **Step 1: Write failing setup error marker tests**

Append to `tests/unit/cli/test_mcrag_cli.py`:

```python
def test_runtime_setup_error_marker_is_lowercase(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ragflow_lite.cli.mcrag import main

    def failing_factory() -> AppServices:
        raise RuntimeError("missing config")

    exit_code = main(
        ["retrieve", "--query", "q", "--json"],
        services_factory=failing_factory,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.err.startswith("setup error: missing config")
```

Append to `tests/unit/agent_runtime/test_setup.py`:

```python
def test_product_skill_uses_case_insensitive_setup_error_guidance(
    tmp_path: Path,
) -> None:
    paths = _paths(tmp_path)
    setup_agent_runtime(paths)
    skill = (
        paths.workspace_dir / ".claude" / "skills" / "microrag-search" / "SKILL.md"
    ).read_text(encoding="utf-8")

    assert "reports a setup error" in skill
    assert "`setup error:`" not in skill
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/cli/test_mcrag_cli.py::test_runtime_setup_error_marker_is_lowercase \
  tests/unit/agent_runtime/test_setup.py::test_product_skill_uses_case_insensitive_setup_error_guidance \
  -q
```

Expected: FAIL because CLI emits `Setup error:` and skill quotes `setup error:`.

- [ ] **Step 3: Normalize CLI stderr marker**

Modify `src/ragflow_lite/cli/mcrag.py`:

```python
    except Exception as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
```

- [ ] **Step 4: Update both skill files**

In `src/ragflow_lite/agent_runtime/skills/microrag-search/SKILL.md` and `.claude/skills/microrag-search/SKILL.md`, replace:

```markdown
If the command fails with `setup error:`, tell the user MicroRAG is not ready in product terms.
```

With:

```markdown
If the command reports a setup error, tell the user MicroRAG is not ready in product terms.
```

- [ ] **Step 5: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/cli/test_mcrag_cli.py \
  tests/unit/agent_runtime/test_setup.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit setup guidance fix**

Run:

```bash
rtk git add src/ragflow_lite/cli/mcrag.py src/ragflow_lite/agent_runtime/skills/microrag-search/SKILL.md .claude/skills/microrag-search/SKILL.md tests/unit/cli/test_mcrag_cli.py tests/unit/agent_runtime/test_setup.py
rtk git commit -m "fix: normalize agent setup error guidance"
```

Expected: commit succeeds.

## Task 4: Simplify Repeated Test Runtime Setup

Purpose: remove repeated test boilerplate introduced by runtime setup without changing behavior.

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/unit/api/test_providers.py`
- Modify: `tests/integration/api/test_ui_shell.py`
- Modify: `tests/unit/api/test_acp_wiring.py`

- [ ] **Step 1: Add shared test helper**

Add this helper near the existing `app_settings` fixture in `tests/conftest.py`:

```python
def setup_test_agent_runtime(tmp_path: Path):
    from ragflow_lite.agent_runtime.setup import (
        default_agent_runtime_paths,
        setup_agent_runtime,
    )

    return setup_agent_runtime(default_agent_runtime_paths(tmp_path))
```

- [ ] **Step 2: Use helper in `app_settings` fixture**

Change `tests/conftest.py`:

```python
@pytest.fixture
def app_settings(tmp_path: Path):
    from ragflow_lite.config import Settings

    paths = setup_test_agent_runtime(tmp_path)
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
        agent_cwd=str(paths.workspace_dir),
        agent_config_dir=str(paths.config_dir),
    )
    assign_isolated_infinity_tables(settings, tmp_path)
    register_infinity_table_cleanup(settings)
    settings.ensure_directories()
    return settings
```

- [ ] **Step 3: Use helper in provider and UI tests**

In `tests/unit/api/test_providers.py`, replace local imports/calls:

```python
from conftest import setup_test_agent_runtime


def _build_settings(tmp_path: Path) -> Settings:
    paths = setup_test_agent_runtime(tmp_path)
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
        agent_cwd=str(paths.workspace_dir),
        agent_config_dir=str(paths.config_dir),
    )
    assign_isolated_infinity_tables(settings, tmp_path)
    settings.ensure_directories()
    return settings
```

In `tests/integration/api/test_ui_shell.py`, replace local imports/calls:

```python
from conftest import setup_test_agent_runtime


def _ui_test_settings(tmp_path: Path) -> Settings:
    paths = setup_test_agent_runtime(tmp_path)
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
        agent_cwd=str(paths.workspace_dir),
        agent_config_dir=str(paths.config_dir),
    )
    assign_isolated_infinity_tables(settings, tmp_path, salt=uuid4().hex[:8])
    register_infinity_table_cleanup(settings)
    settings.ensure_directories()
    return settings
```

In `tests/unit/api/test_acp_wiring.py`, use `setup_test_agent_runtime(tmp_path)` where tests only need default setup. Keep direct `setup_agent_runtime(AgentRuntimePaths(...))` only in tests that intentionally create rogue paths.

- [ ] **Step 4: Run affected tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/api/test_acp_wiring.py \
  tests/unit/api/test_providers.py \
  tests/integration/api/test_ui_shell.py \
  tests/unit/agent_runtime/test_setup.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit test simplification**

Run:

```bash
rtk git add tests/conftest.py tests/unit/api/test_providers.py tests/integration/api/test_ui_shell.py tests/unit/api/test_acp_wiring.py
rtk git commit -m "test: simplify agent runtime setup fixtures"
```

Expected: commit succeeds.

## Task 5: Update Active Contract

Purpose: make the infrastructure contract reflect lazy ACP construction and strict product-owned path validation.

**Files:**
- Modify: `src/ragflow_lite/infrastructure/CONTRACTS.md`

- [ ] **Step 1: Update ACP runtime contract bullets**

In `src/ragflow_lite/infrastructure/CONTRACTS.md`, replace:

```markdown
- `AcpClient` is wired into `AppServices` via `_build_acp_client(settings)` in `build_services()`. Settings fields: `agent_command` (env `MICRORAG_AGENT_COMMAND`, default `"claude"`), `agent_args` (env `MICRORAG_AGENT_ARGS`, default `"--acp --setting-sources project,local"`), `agent_cwd` (env `MICRORAG_AGENT_CWD`, default `data/agent-runtime/workspace`), and `agent_config_dir` (env `MICRORAG_AGENT_CONFIG_DIR` or `CLAUDE_CONFIG_DIR`, default `data/agent-runtime/config`).
- Product agent runtime files are generated from `src/ragflow_lite/agent_runtime/` by `mcrag agent setup`. `data/agent-runtime/` is runtime state and is not the source of truth.
- ACP child processes receive `CLAUDE_CONFIG_DIR`, `PATH`, and `PYTHONPATH` through `AcpRuntimeConfig.env`.
```

With:

```markdown
- `AppServices` stores an ACP client factory and constructs `AcpClient` lazily when agent routes first access `services.acp_client`; non-agent service construction must not require `data/agent-runtime/`.
- Settings fields: `agent_command` (env `MICRORAG_AGENT_COMMAND`, default `"claude"`), `agent_args` (env `MICRORAG_AGENT_ARGS`, default `"--acp --setting-sources project,local"`), `agent_cwd` (env `MICRORAG_AGENT_CWD`, default `data/agent-runtime/workspace`), and `agent_config_dir` (env `MICRORAG_AGENT_CONFIG_DIR`, default `data/agent-runtime/config`).
- Product agent runtime files are generated from `src/ragflow_lite/agent_runtime/` by `mcrag agent setup`. `data/agent-runtime/` is runtime state and is not the source of truth.
- `_build_acp_client(settings)` rejects runtime paths that do not resolve to the project-owned defaults from `default_agent_runtime_paths(settings.project_root)`.
- ACP child processes receive `CLAUDE_CONFIG_DIR`, `PATH`, and `PYTHONPATH` through `AcpRuntimeConfig.env`.
```

Add forbidden stale interpretation:

```markdown
- Do not let ambient parent-shell `CLAUDE_CONFIG_DIR` select product runtime config.
```

- [ ] **Step 2: Scan for stale contract text**

Run:

```bash
rg -n "or `CLAUDE_CONFIG_DIR`|falls back to `project_root`|non-agent service construction.*require|ambient parent-shell" src/ragflow_lite/infrastructure/CONTRACTS.md
```

Expected:

- no `or CLAUDE_CONFIG_DIR` settings-source text remains;
- no project-root fallback text remains;
- only the new intended lazy/non-agent and ambient-shell wording appears.

- [ ] **Step 3: Commit contract fix**

Run:

```bash
rtk git add src/ragflow_lite/infrastructure/CONTRACTS.md
rtk git commit -m "docs: clarify lazy agent runtime contract"
```

Expected: commit succeeds.

## Task 6: Verification and Review

Purpose: verify the blocking review findings are fixed and no new regressions were introduced.

**Files:**
- Verify: all changed files

- [ ] **Step 1: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/unit/agent_runtime/test_setup.py \
  tests/unit/api/test_acp_wiring.py \
  tests/unit/api/test_providers.py \
  tests/unit/api/test_agent_routes.py \
  tests/unit/cli/test_mcrag_cli.py \
  tests/unit/infrastructure/test_acp_client_redaction.py \
  tests/integration/api/test_ui_shell.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass. Report exact pass/skip counts.

- [ ] **Step 3: Run ruff on changed files**

Run:

```bash
.venv/bin/python -m ruff check \
  src/ragflow_lite/agent_runtime \
  src/ragflow_lite/api/deps/providers.py \
  src/ragflow_lite/config/settings.py \
  src/ragflow_lite/cli/mcrag.py \
  tests/conftest.py \
  tests/unit/agent_runtime/test_setup.py \
  tests/unit/api/test_acp_wiring.py \
  tests/unit/api/test_providers.py \
  tests/unit/api/test_agent_routes.py \
  tests/unit/cli/test_mcrag_cli.py \
  tests/integration/api/test_ui_shell.py
```

Expected: no lint errors in changed files.

- [ ] **Step 4: Verify fresh checkout non-agent behavior no longer needs setup**

Run:

```bash
rm -rf data/agent-runtime
.venv/bin/python -m pytest tests/unit/api/test_providers.py::test_build_services_does_not_require_agent_runtime_setup -q
```

Expected: PASS.

- [ ] **Step 5: Verify agent path still fails clearly without setup**

Run:

```bash
.venv/bin/python -m pytest tests/unit/api/test_acp_wiring.py::TestBuildAcpClient::test_requires_agent_runtime_workspace_when_cwd_missing -q
```

Expected: PASS and assertion uses `SETUP_INCOMPLETE_MESSAGE`.

- [ ] **Step 6: Re-run forbidden asset scan after setup**

Run:

```bash
.venv/bin/python -m ragflow_lite.cli.mcrag agent setup --project-root /home/xia/ragflow-lite
rg -n "AGENTS.md|CONTRACTS.md|cx |pytest|git workflow|code-review|Claude Code|--mode standard|mcrag answer" data/agent-runtime/workspace
```

Expected: setup command succeeds and `rg` has no matches.

- [ ] **Step 7: Request final code review**

Dispatch a reviewer with:

```text
Base: d88d94099e3bfe16cb67c656761f6dca50334fdc
Head: <current HEAD after fix commits>
Scope: fixes for lazy ACP construction, strict runtime path validation, setup error wording, and test simplification.
Requirements: non-agent paths must work without runtime setup; agent paths must validate product-owned runtime paths; product skill remains DiscoRAG-only and does not expose mcrag answer or standard mode.
```

Expected: no Critical or Important findings.

## Self-Review

- Review blocker coverage:
  - Non-agent regression from eager ACP setup: Task 1 and Task 6.
  - Path isolation bypass through env overrides: Task 2 and Task 5.
  - Setup error marker mismatch: Task 3.
  - Centralized setup message drift: Task 2.
  - Repeated test setup boilerplate: Task 4.
- Scope control:
  - No change to retrieval JSON shape.
  - No change to `mcrag answer` availability.
  - No change to UI design.
  - No MCP work.
- Placeholder scan:
  - No `TBD`, `TODO`, `implement later`, or vague "handle edge cases" steps.
- Type consistency:
  - `AppServices.acp_client_factory` is `Callable[[], AcpClient]`.
  - `AppServices.acp_client` remains the property used by existing agent routes.
  - `validate_agent_runtime_paths()` and `validate_agent_runtime_workspace()` both raise `SETUP_INCOMPLETE_MESSAGE` for invalid product runtime paths.
