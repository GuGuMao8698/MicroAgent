# MicroRAG MicroAgent Runtime Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the working local agent runtime from `参考项目/claude-code` into a MicroRAG-owned `src/ragflow_lite/microagent` runtime bundle and make active launch/default wiring use `MicroAgent`.

**Architecture:** Copy the source runtime tree first, then prune generated/project-management files and clean external identity surfaces. Keep three path roles separate: the MicroAgent bundle under `src/ragflow_lite/microagent`, the product conversation workspace under `data/agent-runtime/workspace`, and the product config directory under `data/agent-runtime/config`.

**Tech Stack:** Python, pytest, FastAPI ACP wiring, Bash launcher, Bun/TypeScript runtime bundle, setuptools package discovery, gitignore-based local state exclusion.

---

## Implementation Decisions

- `src/ragflow_lite/microagent` is created by copying `参考项目/claude-code` and pruning it. Do not hand-build a new runtime skeleton.
- `src/ragflow_lite/microagent/.claude/settings.json` is copied from the source runtime, is not content-inspected, and is added to `.gitignore` after the copy has been verified.
- `src/ragflow_lite/microagent/.claude/skills/` and `src/ragflow_lite/microagent/.claude/agents/` are copied as runtime assets.
- `.claude/skills/.drafts/` is copied first, then inspected and classified during pruning.
- `vendor/audio-capture-src/` is retained with `vendor/audio-capture/` because it may be needed for native addon rebuild support.
- `progress.md` is excluded as source-project progress state.
- `setup_agent_runtime()` continues to prepare product workspace/config/shim state only. It must not copy, create, or populate `src/ragflow_lite/microagent`.
- `default_agent_runtime_paths()` returns separate `microagent_dir`, `workspace_dir`, and `config_dir` paths.
- `Settings.default()` defaults `agent_command` to `scripts/run_microagent.sh`, `agent_args` to `--acp --setting-sources project`, `agent_cwd` to `data/agent-runtime/workspace`, `agent_config_dir` to `data/agent-runtime/config`, and `microagent_dir` to `src/ragflow_lite/microagent`.
- Product workspace seeding is not changed to read from the bundle. Existing local `data/agent-runtime/workspace` content remains the product conversation context source.
- Active contract docs are updated only after source behavior and tests are updated.

## File Structure

- Create: `src/ragflow_lite/microagent/`
  - Bundled Bun/TypeScript runtime copied from `参考项目/claude-code`, then pruned.
- Create: `src/ragflow_lite/microagent/README.md`
  - Short MicroRAG-owned note explaining how the bundle should be launched.
- Delete: `scripts/run_reference_claude_code.sh`
  - Old active launcher name.
- Create: `scripts/run_microagent.sh`
  - Renamed launcher targeting `src/ragflow_lite/microagent`.
- Modify: `.gitignore`
  - Ignore copied local runtime settings and generated bundle state.
- Modify: `src/ragflow_lite/config/settings.py`
  - Add `microagent_dir`; update agent command/cwd defaults.
- Modify: `src/ragflow_lite/agent_runtime/setup.py`
  - Add `microagent_dir` to `AgentRuntimePaths`; keep setup scoped to workspace/config/shim; validate bundle assets without creating them.
- Modify: `src/ragflow_lite/cli/mcrag.py`
  - Include `microagent_dir` in `mcrag agent setup` JSON output.
- Modify: `src/ragflow_lite/api/deps/providers.py`
  - Pass `microagent_dir` into runtime path validation.
- Modify: `src/ragflow_lite/agent_runtime/__init__.py`
  - Export updated path dataclass shape if needed.
- Rename: `tests/unit/test_reference_claude_code_script.py` -> `tests/unit/test_microagent_script.py`
  - Retarget launcher behavior tests.
- Modify: `tests/helpers/agent_runtime.py`
  - Create minimal test bundle/workspace/config shape.
- Modify: `tests/unit/agent_runtime/test_setup.py`
  - Update default path, validation, idempotence, and env tests.
- Modify: `tests/unit/api/test_acp_wiring.py`
  - Update Settings defaults and `_build_acp_client()` wiring assertions.
- Modify: `tests/unit/cli/test_mcrag_cli.py`
  - Update agent setup expectations for workspace/config/shim rather than reference runtime materialization.
- Modify: `tests/unit/api/test_providers.py`, `tests/conftest.py`, `tests/integration/api/test_ui_shell.py`
  - Pass `microagent_dir` anywhere tests construct runtime-backed `Settings`.
- Modify: `src/ragflow_lite/infrastructure/CONTRACTS.md`
  - Update active contract once behavior is source-backed.

---

### Task 1: Copy And Prune The Runtime Bundle

**Files:**
- Create: `src/ragflow_lite/microagent/`
- Create: `src/ragflow_lite/microagent/README.md`
- Modify after copy: `src/ragflow_lite/microagent/package.json`
- Modify after copy: `src/ragflow_lite/microagent/CLAUDE.md`
- Modify after copy: `src/ragflow_lite/microagent/AGENTS.md`

- [ ] **Step 1: Copy the source runtime tree**

Run from repo root:

```bash
rtk proxy mkdir -p src/ragflow_lite
rtk proxy rsync -a '参考项目/claude-code/' 'src/ragflow_lite/microagent/'
```

Expected: the source runtime tree is copied before pruning. `src/ragflow_lite/microagent/.claude/settings.json` exists at this point and has not yet been added to `.gitignore`.

- [ ] **Step 2: Prune excluded repository, dependency, generated, and local state**

Verify the prune target first:

```bash
rtk proxy test -d src/ragflow_lite/microagent
rtk proxy test -f src/ragflow_lite/microagent/package.json
```

Run:

```bash
rtk proxy rm -rf \
  src/ragflow_lite/microagent/.git \
  src/ragflow_lite/microagent/.github \
  src/ragflow_lite/microagent/.vscode \
  src/ragflow_lite/microagent/.husky \
  src/ragflow_lite/microagent/.deepeval \
  src/ragflow_lite/microagent/dist \
  src/ragflow_lite/microagent/node_modules \
  src/ragflow_lite/microagent/docs \
  src/ragflow_lite/microagent/spec \
  src/ragflow_lite/microagent/tests \
  src/ragflow_lite/microagent/teach-me \
  src/ragflow_lite/microagent/.claude/settings.local.json \
  src/ragflow_lite/microagent/.claude/.credentials* \
  src/ragflow_lite/microagent/.claude/.cache \
  src/ragflow_lite/microagent/.claude/cache \
  src/ragflow_lite/microagent/.claude/history \
  src/ragflow_lite/microagent/.claude/transcripts \
  src/ragflow_lite/microagent/.claude/projects \
  src/ragflow_lite/microagent/.claude/todos
```

Expected: generated dependencies, nested repo state, upstream management dirs, and local `.claude` state are absent after the command.

- [ ] **Step 3: Inspect and classify `.claude/skills/.drafts/`**

Run:

```bash
rtk proxy find src/ragflow_lite/microagent/.claude/skills/.drafts -maxdepth 3 -type f -print 2>/dev/null || true
```

Expected: if only draft/example skill files are listed, remove the draft bucket with:

```bash
rtk proxy rm -rf src/ragflow_lite/microagent/.claude/skills/.drafts
```

If the inspection finds runtime-required skill material, keep the specific file and record the reason in the implementation report.

- [ ] **Step 4: Remove copied presentation/progress files**

Run:

```bash
rtk proxy rm -f \
  src/ragflow_lite/microagent/README.md \
  src/ragflow_lite/microagent/README_EN.md \
  src/ragflow_lite/microagent/SECURITY.md \
  src/ragflow_lite/microagent/DEV-LOG.md \
  src/ragflow_lite/microagent/Friends.md \
  src/ragflow_lite/microagent/codecov.yml \
  src/ragflow_lite/microagent/contributors.svg \
  src/ragflow_lite/microagent/.impeccable.md \
  src/ragflow_lite/microagent/docs.json \
  src/ragflow_lite/microagent/mint.json \
  src/ragflow_lite/microagent/progress.md
```

Expected: upstream presentation files and `progress.md` are absent after the command.

- [ ] **Step 5: Add a MicroRAG-owned bundle README**

Create `src/ragflow_lite/microagent/README.md` with exactly:

```markdown
# MicroAgent Runtime Bundle

This directory contains the bundled local agent runtime used by MicroRAG's
agent shell. Product code should launch it through `scripts/run_microagent.sh`
or the MicroRAG agent runtime wiring, not by invoking files here directly.
```

- [ ] **Step 6: Inspect copied internal runtime docs before cleaning**

Run:

```bash
rtk rg -n "Claude Code|claude-code|reference|参考项目|github|README|install|contribute|identity|prompt" \
  src/ragflow_lite/microagent/CLAUDE.md \
  src/ragflow_lite/microagent/AGENTS.md
```

Expected: output identifies stale source-project framing and external-facing instructions to clean. Do not inspect or modify `src/ragflow_lite/microagent/.claude/settings.json`.

- [ ] **Step 7: Clean copied internal runtime docs in place**

Edit only the stale framing found in Step 6. Keep runtime-relevant instructions from the copied `CLAUDE.md` and `AGENTS.md`; do not replace the files with a generic template. The cleaned files must retain this boundary in natural wording:

```text
This file belongs to the bundled MicroAgent runtime source tree.
It is not the MicroRAG product conversation instruction source.
Product conversation context remains owned by data/agent-runtime/workspace.
```

- [ ] **Step 8: Clean package metadata while preserving runtime scripts and dependencies**

Run:

```bash
rtk proxy node <<'NODE'
const fs = require("fs");
const path = "src/ragflow_lite/microagent/package.json";
const pkg = JSON.parse(fs.readFileSync(path, "utf8"));
pkg.name = "microrag-microagent-runtime";
pkg.private = true;
pkg.description = "Bundled local agent runtime for MicroRAG.";
delete pkg.repository;
delete pkg.homepage;
delete pkg.bugs;
delete pkg.funding;
if (pkg.bin) {
  const existing = pkg.bin["claude-code-best"] || pkg.bin["ccb"] || pkg.bin["ccb-bun"];
  pkg.bin = existing ? { "microagent": existing } : {};
}
fs.writeFileSync(path, JSON.stringify(pkg, null, 2) + "\n");
NODE
```

Expected: `scripts`, `dependencies`, `devDependencies`, and build/runtime config remain present; upstream repository/homepage/bugs/funding metadata is gone.

- [ ] **Step 9: Verify required copied runtime paths and exclusions**

Run:

```bash
rtk proxy test -d src/ragflow_lite/microagent/src
rtk proxy test -d src/ragflow_lite/microagent/packages
rtk proxy test -d src/ragflow_lite/microagent/scripts
rtk proxy test -d src/ragflow_lite/microagent/vendor/audio-capture
rtk proxy test -d src/ragflow_lite/microagent/vendor/audio-capture-src
rtk proxy test -f src/ragflow_lite/microagent/package.json
rtk proxy test -f src/ragflow_lite/microagent/bun.lock
rtk proxy test -f src/ragflow_lite/microagent/bunfig.toml
rtk proxy test -f src/ragflow_lite/microagent/tsconfig.base.json
rtk proxy test -f src/ragflow_lite/microagent/tsconfig.json
rtk proxy test -f src/ragflow_lite/microagent/biome.json
rtk proxy test -f src/ragflow_lite/microagent/build.ts
rtk proxy test -f src/ragflow_lite/microagent/vite.config.ts
rtk proxy test -f src/ragflow_lite/microagent/knip.json
rtk proxy test -f src/ragflow_lite/microagent/.claude/settings.json
rtk proxy test -d src/ragflow_lite/microagent/.claude/skills
rtk proxy test -d src/ragflow_lite/microagent/.claude/agents
```

Run:

```bash
rtk proxy find src/ragflow_lite/microagent \( \
  -name .git -o \
  -name .github -o \
  -name node_modules -o \
  -name dist -o \
  -path '*/.claude/settings.local.json' -o \
  -path '*/.claude/.credentials*' -o \
  -path '*/.claude/.cache*' -o \
  -path '*/.claude/cache*' -o \
  -path '*/.claude/history*' -o \
  -path '*/.claude/transcripts*' -o \
  -path '*/.claude/projects*' -o \
  -path '*/.claude/todos*' -o \
  -path '*/.claude/skills/.drafts' \
\) -print
```

Expected: the first command group exits 0; the `find` command prints nothing.

---

### Task 2: Add MicroAgent Bundle Ignore Rules

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Verify copied settings exists before ignoring it**

Run:

```bash
rtk proxy test -f src/ragflow_lite/microagent/.claude/settings.json
```

Expected: command exits 0. Do not inspect the file contents.

- [ ] **Step 2: Add bundle-local ignore rules**

Append this block near the existing local runtime ignores in `.gitignore`:

```gitignore
# MicroAgent bundled runtime local/generated state
src/ragflow_lite/microagent/.claude/settings.json
src/ragflow_lite/microagent/.claude/settings.local.json
src/ragflow_lite/microagent/.claude/.credentials*
src/ragflow_lite/microagent/.claude/.cache/
src/ragflow_lite/microagent/.claude/cache/
src/ragflow_lite/microagent/.claude/history/
src/ragflow_lite/microagent/.claude/transcripts/
src/ragflow_lite/microagent/.claude/projects/
src/ragflow_lite/microagent/.claude/todos/
src/ragflow_lite/microagent/node_modules/
src/ragflow_lite/microagent/dist/
src/ragflow_lite/microagent/.deepeval/
```

- [ ] **Step 3: Verify the exact settings file is ignored**

Run:

```bash
rtk git check-ignore -v src/ragflow_lite/microagent/.claude/settings.json
```

Expected: output includes the new `.gitignore` rule for `src/ragflow_lite/microagent/.claude/settings.json`.

- [ ] **Step 4: Verify runtime source files are not globally ignored**

Run:

```bash
rtk git check-ignore -v src/ragflow_lite/microagent/package.json src/ragflow_lite/microagent/src/entrypoints/cli.tsx || true
```

Expected: no ignore output for `package.json` or `src/entrypoints/cli.tsx`.

---

### Task 3: Rename And Retarget The Launcher

**Files:**
- Delete: `scripts/run_reference_claude_code.sh`
- Create: `scripts/run_microagent.sh`
- Test: `tests/unit/test_microagent_script.py`

- [ ] **Step 1: Rename the launcher file**

Run:

```bash
rtk proxy mv scripts/run_reference_claude_code.sh scripts/run_microagent.sh
```

Expected: `scripts/run_microagent.sh` exists and `scripts/run_reference_claude_code.sh` is absent.

- [ ] **Step 2: Replace launcher content with MicroAgent path ownership**

Replace `scripts/run_microagent.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MICROAGENT_DIR="${MICRORAG_MICROAGENT_DIR:-$ROOT/src/ragflow_lite/microagent}"
PRODUCT_WORKSPACE="${MICRORAG_AGENT_CWD:-$ROOT/data/agent-runtime/workspace}"
PRODUCT_CONFIG_DIR="${MICRORAG_AGENT_CONFIG_DIR:-$ROOT/data/agent-runtime/config}"

die() {
  echo "setup error: $*" >&2
  exit 2
}

if ! command -v bun >/dev/null 2>&1; then
  die "bun command not found in PATH"
fi

if [[ ! -d "$MICROAGENT_DIR" ]]; then
  die "missing MicroAgent runtime bundle: $MICROAGENT_DIR"
fi

if [[ ! -d "$MICROAGENT_DIR/node_modules" ]]; then
  echo "setup error: missing $MICROAGENT_DIR/node_modules" >&2
  echo "Run: cd \"$MICROAGENT_DIR\" && bun install" >&2
  exit 2
fi

LOCAL_ENV="$ROOT/data/agent-runtime/local.env"
RUNTIME_BIN="$ROOT/data/agent-runtime/bin"
USER_BIN="${HOME:-}/.local/bin"
if [[ -f "$LOCAL_ENV" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$LOCAL_ENV"
  set +a
else
  die "missing $LOCAL_ENV"
fi

require_env() {
  local missing=()
  local name
  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      missing+=("$name")
    fi
  done
  if ((${#missing[@]} > 0)); then
    echo "setup error: missing required environment variables: ${missing[*]}" >&2
    echo "Fill them in $LOCAL_ENV and rerun this script." >&2
    exit 2
  fi
}

require_env \
  DEEPSEEK_API_KEY \
  ARK_API_KEY \
  ARK_EMBEDDING_MODEL \
  ANTHROPIC_AUTH_TOKEN \
  ANTHROPIC_BASE_URL \
  ANTHROPIC_DEFAULT_HAIKU_MODEL \
  ANTHROPIC_DEFAULT_SONNET_MODEL \
  ANTHROPIC_DEFAULT_OPUS_MODEL

require_local_settings() {
  local settings_path="$MICROAGENT_DIR/.claude/settings.json"
  if [[ ! -f "$settings_path" ]]; then
    echo "setup error: missing $settings_path" >&2
    echo "Copy this local-only file from the source runtime before starting MicroAgent." >&2
    exit 2
  fi
}

install_user_mcrag_shim() {
  if [[ -z "${HOME:-}" ]]; then
    return
  fi
  mkdir -p "$USER_BIN"
  ln -sfn "$RUNTIME_BIN/mcrag" "$USER_BIN/mcrag"
}

run_microagent() {
  cd "$MICROAGENT_DIR"
  export PATH="$USER_BIN:$RUNTIME_BIN:$ROOT/.venv/bin:$PATH"
  export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$PRODUCT_CONFIG_DIR}"
  export MICRORAG_AGENT_CWD="$PRODUCT_WORKSPACE"
  export MICRORAG_AGENT_CONFIG_DIR="$PRODUCT_CONFIG_DIR"
  export MICRORAG_MICROAGENT_DIR="$MICROAGENT_DIR"
  require_local_settings
  exec bun --silent run dev -- "$@"
}

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  die "missing $ROOT/.venv/bin/python"
fi

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
"$ROOT/.venv/bin/python" -m ragflow_lite.cli.mcrag agent setup --project-root "$ROOT" >/dev/null
install_user_mcrag_shim

if (($# > 0)); then
  run_microagent "$@"
fi

HOST="${MICRORAG_HOST:-127.0.0.1}"
PORT="${MICRORAG_PORT:-8001}"

export CLAUDE_CONFIG_DIR="$PRODUCT_CONFIG_DIR"
export MICRORAG_AGENT_CWD="$PRODUCT_WORKSPACE"
export MICRORAG_AGENT_CONFIG_DIR="$PRODUCT_CONFIG_DIR"
export MICRORAG_MICROAGENT_DIR="$MICROAGENT_DIR"
export MICRORAG_AGENT_COMMAND="${MICRORAG_AGENT_COMMAND:-$ROOT/scripts/run_microagent.sh}"
export MICRORAG_AGENT_ARGS="${MICRORAG_AGENT_ARGS:---acp --setting-sources project}"
export PATH="$USER_BIN:$RUNTIME_BIN:$ROOT/.venv/bin:$PATH"

require_local_settings

if [[ "${MICRORAG_DEMO_DRY_RUN:-}" == "1" ]]; then
  echo "agent setup: $ROOT/.venv/bin/python -m ragflow_lite.cli.mcrag agent setup --project-root $ROOT"
  echo "microagent bundle: $MICROAGENT_DIR"
  echo "agent settings: $MICROAGENT_DIR/.claude/settings.json"
  echo "backend: $ROOT/.venv/bin/python -m uvicorn ragflow_lite.app:app --host $HOST --port $PORT --reload"
  echo "ui: http://$HOST:$PORT/agent"
  echo "agent command: $MICRORAG_AGENT_COMMAND"
  echo "agent args: $MICRORAG_AGENT_ARGS"
  echo "agent cwd: $MICRORAG_AGENT_CWD"
  echo "agent config: $CLAUDE_CONFIG_DIR"
  exit 0
fi

"$ROOT/.venv/bin/python" -m uvicorn ragflow_lite.app:app \
  --host "$HOST" \
  --port "$PORT" \
  --reload &
UVICORN_PID=$!

sleep 2
if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
  die "MicroRAG backend failed to start on $HOST:$PORT"
fi

cleanup() {
  kill "$UVICORN_PID" 2>/dev/null || true
}
trap cleanup EXIT

echo "MicroRAG UI: http://$HOST:$PORT/agent"
echo "MicroAgent runtime: $MICROAGENT_DIR"
echo "Agent command: $MICRORAG_AGENT_COMMAND"
echo "Agent args: $MICRORAG_AGENT_ARGS"
echo "Agent cwd: $MICRORAG_AGENT_CWD"
echo "Agent config: $CLAUDE_CONFIG_DIR"
echo "Agent settings: $MICROAGENT_DIR/.claude/settings.json"
echo "Use /status in MicroAgent to verify settings sources."

read -r -a DEFAULT_AGENT_ARGV <<< "$MICRORAG_AGENT_ARGS"
run_microagent "${DEFAULT_AGENT_ARGV[@]}"
```

- [ ] **Step 3: Make the renamed launcher executable**

Run:

```bash
rtk proxy chmod +x scripts/run_microagent.sh
```

Expected: `rtk proxy test -x scripts/run_microagent.sh` exits 0.

---

### Task 4: Update Runtime Path Contracts In Python

**Files:**
- Modify: `src/ragflow_lite/agent_runtime/setup.py`
- Modify: `src/ragflow_lite/config/settings.py`
- Modify: `src/ragflow_lite/cli/mcrag.py`
- Modify: `src/ragflow_lite/api/deps/providers.py`
- Modify if needed: `src/ragflow_lite/agent_runtime/__init__.py`
- Test: `tests/unit/agent_runtime/test_setup.py`
- Test: `tests/unit/api/test_acp_wiring.py`

- [ ] **Step 1: Extend `AgentRuntimePaths`**

In `src/ragflow_lite/agent_runtime/setup.py`, update the dataclass and defaults to this shape:

```python
@dataclass(frozen=True, slots=True)
class AgentRuntimePaths:
    project_root: Path
    config_dir: Path
    workspace_dir: Path
    microagent_dir: Path


def default_agent_runtime_paths(project_root: Path) -> AgentRuntimePaths:
    root = project_root.resolve()
    runtime_root = root / "data" / "agent-runtime"
    microagent_runtime = os.getenv("MICRORAG_MICROAGENT_DIR")
    return AgentRuntimePaths(
        project_root=root,
        config_dir=runtime_root / "config",
        workspace_dir=runtime_root / "workspace",
        microagent_dir=(
            Path(microagent_runtime).expanduser()
            if microagent_runtime is not None and microagent_runtime.strip()
            else root / "src" / "ragflow_lite" / "microagent"
        ),
    )
```

- [ ] **Step 2: Keep setup scoped to config/workspace/shim**

In `setup_agent_runtime()`, ensure it creates `config_dir` and `workspace_dir`, writes the shim, and does not create or populate `microagent_dir`:

```python
def setup_agent_runtime(paths: AgentRuntimePaths) -> AgentRuntimePaths:
    paths.config_dir.mkdir(parents=True, exist_ok=True)
    paths.workspace_dir.mkdir(parents=True, exist_ok=True)
    _write_mcrag_shim(paths)
    _migrate_legacy_workspace_assets(paths)
    return paths
```

Keep `_migrate_legacy_workspace_assets()` as a product workspace migration only. It should copy from `data/agent-runtime/workspace` to `paths.workspace_dir` only when those are different, and it must not copy anything into `paths.microagent_dir`.

- [ ] **Step 3: Update runtime path validation**

In `validate_agent_runtime_paths()` and `validate_agent_runtime_workspace()`, validate the split paths:

```python
def validate_agent_runtime_paths(paths: AgentRuntimePaths) -> None:
    expected = default_agent_runtime_paths(paths.project_root)
    if not _same_path(paths.config_dir, expected.config_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
    if not _same_path(paths.workspace_dir, expected.workspace_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
    if not _same_path(paths.microagent_dir, expected.microagent_dir):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)


def validate_agent_runtime_workspace(paths: AgentRuntimePaths) -> None:
    validate_agent_runtime_paths(paths)
    microagent_claude_dir = paths.microagent_dir / ".claude"
    required = (
        paths.config_dir,
        paths.workspace_dir,
        paths.microagent_dir,
        microagent_claude_dir / "skills",
        microagent_claude_dir / "agents",
    )
    if not all(path.exists() for path in required):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)
    settings_path = microagent_claude_dir / "settings.json"
    if not settings_path.exists():
        raise RuntimeError(
            LOCAL_SETTINGS_REQUIRED_MESSAGE.format(settings_path=settings_path)
        )
```

- [ ] **Step 4: Add `microagent_dir` to `Settings`**

In `src/ragflow_lite/config/settings.py`, add:

```python
    microagent_dir: str | None = field(
        default_factory=lambda: _read_optional_env("MICRORAG_MICROAGENT_DIR")
    )
```

Update `Settings.default()` agent defaults:

```python
        default_microagent_dir = root / "src" / "ragflow_lite" / "microagent"
        default_agent_cwd = runtime_root / "workspace"
        default_agent_command = root / "scripts" / "run_microagent.sh"
        return cls(
            project_root=root,
            uploads_dir=root / "data" / "uploads",
            local_index_dir=root / "data" / "local_index",
            temp_dir=root / "data" / "tmp",
            agent_command=(
                _read_optional_env("MICRORAG_AGENT_COMMAND")
                or str(default_agent_command)
            ),
            agent_cwd=(
                _read_optional_env("MICRORAG_AGENT_CWD") or str(default_agent_cwd)
            ),
            agent_config_dir=(
                _read_optional_env("MICRORAG_AGENT_CONFIG_DIR")
                or str(runtime_root / "config")
            ),
            microagent_dir=(
                _read_optional_env("MICRORAG_MICROAGENT_DIR")
                or str(default_microagent_dir)
            ),
        )
```

Remove the `MICRORAG_REFERENCE_CLAUDE_CODE_DIR` default path branch from `Settings.default()`.

- [ ] **Step 5: Update ACP client construction**

In `src/ragflow_lite/api/deps/providers.py`, update the guard and paths:

```python
    if (
        settings.agent_cwd is None
        or settings.agent_config_dir is None
        or settings.microagent_dir is None
    ):
        raise RuntimeError(SETUP_INCOMPLETE_MESSAGE)

    paths = AgentRuntimePaths(
        project_root=settings.project_root,
        config_dir=Path(settings.agent_config_dir),
        workspace_dir=Path(settings.agent_cwd),
        microagent_dir=Path(settings.microagent_dir),
    )
```

Keep `AcpRuntimeConfig.cwd` as `str(paths.workspace_dir)` so backend conversation state remains separate from the bundle process cwd.

- [ ] **Step 6: Include `microagent_dir` in CLI setup output**

In `src/ragflow_lite/cli/mcrag.py`, update `_handle_agent_setup()`:

```python
    _write_json(
        {
            "config_dir": str(paths.config_dir),
            "workspace_dir": str(paths.workspace_dir),
            "microagent_dir": str(paths.microagent_dir),
        }
    )
```

- [ ] **Step 7: Verify import/export shape**

Run:

```bash
rtk proxy .venv/bin/python - <<'PY'
from pathlib import Path
from ragflow_lite.agent_runtime.setup import default_agent_runtime_paths
paths = default_agent_runtime_paths(Path.cwd())
print(paths.workspace_dir)
print(paths.microagent_dir)
PY
```

Expected: first printed path ends with `data/agent-runtime/workspace`; second printed path ends with `src/ragflow_lite/microagent`.

---

### Task 5: Retarget Launcher Tests

**Files:**
- Rename: `tests/unit/test_reference_claude_code_script.py` -> `tests/unit/test_microagent_script.py`

- [ ] **Step 1: Rename the test file**

Run:

```bash
rtk proxy mv tests/unit/test_reference_claude_code_script.py tests/unit/test_microagent_script.py
```

- [ ] **Step 2: Update the script fixture layout**

In `tests/unit/test_microagent_script.py`, update `_make_script_repo()` so it creates `src/ragflow_lite/microagent` instead of `参考项目/claude-code`:

```python
def _make_script_repo(tmp_path: Path, *, with_settings: bool = True) -> Path:
    source_root = Path.cwd()
    repo_root = tmp_path / "repo"
    script_dir = repo_root / "scripts"
    microagent_dir = repo_root / "src" / "ragflow_lite" / "microagent"
    node_modules = microagent_dir / "node_modules"

    script_dir.mkdir(parents=True)
    node_modules.mkdir(parents=True)
    (microagent_dir / ".claude" / "skills" / "teach-me").mkdir(parents=True)
    (microagent_dir / ".claude" / "agents").mkdir(parents=True)
    (microagent_dir / ".claude" / "skills" / "teach-me" / "SKILL.md").write_text(
        "---\nname: teach-me\n---\n# Teach Me\n",
        encoding="utf-8",
    )
    (microagent_dir / ".claude" / "agents" / "hello-agent.md").write_text(
        "---\nname: hello-agent\n---\nhello\n",
        encoding="utf-8",
    )
    local_env = repo_root / "data" / "agent-runtime" / "local.env"
    local_env.parent.mkdir(parents=True)
    local_env.write_text("", encoding="utf-8")
    shutil.copyfile(
        source_root / "scripts" / "run_microagent.sh",
        script_dir / "run_microagent.sh",
    )
    python_bin = repo_root / ".venv" / "bin"
    python_bin.mkdir(parents=True)
    (python_bin / "python").write_text(
        "#!/usr/bin/env bash\nexit 0\n", encoding="utf-8"
    )
    (python_bin / "python").chmod(0o755)

    if with_settings:
        settings_dir = microagent_dir / ".claude"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "settings.json").write_text(
            '{"permissions":{"defaultMode":"bypassPermissions"}}\n',
            encoding="utf-8",
        )

    return repo_root
```

- [ ] **Step 3: Remove the legacy migration test**

Delete the test that asserts legacy workspace assets are copied into `参考项目/claude-code`. Replace it with:

```python
def test_microagent_script_uses_bundle_settings_not_product_workspace_settings(
    tmp_path: Path,
) -> None:
    repo_root = _make_script_repo(tmp_path, with_settings=True)
    _write_required_local_env(repo_root)
    product_workspace = repo_root / "data" / "agent-runtime" / "workspace"
    (product_workspace / ".claude").mkdir(parents=True)
    (product_workspace / ".claude" / "settings.json").write_text(
        '{"product":true}\n',
        encoding="utf-8",
    )
    log_path = tmp_path / "calls.log"
    env = {
        **_base_env(tmp_path, log_path),
        "MICRORAG_DEMO_DRY_RUN": "1",
    }

    result = subprocess.run(
        ["bash", str(repo_root / "scripts" / "run_microagent.sh")],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert (
        f"agent settings: {repo_root / 'src' / 'ragflow_lite' / 'microagent' / '.claude' / 'settings.json'}"
        in result.stdout
    )
```

- [ ] **Step 4: Update remaining test names and assertions**

Apply these replacements in the renamed test file:

```text
test_reference_script_acp_args_only_launch_reference_runtime
-> test_microagent_script_acp_args_only_launch_bundle_runtime

test_reference_script_acp_args_source_local_env_for_agent_provider
-> test_microagent_script_acp_args_source_local_env_for_agent_provider

test_reference_script_dry_run_shows_full_demo_bootstrap
-> test_microagent_script_dry_run_shows_full_demo_bootstrap

test_reference_script_requires_local_workspace_settings
-> test_microagent_script_requires_bundle_settings

scripts/run_reference_claude_code.sh
-> scripts/run_microagent.sh

参考项目/claude-code
-> src/ragflow_lite/microagent

Reference Claude Code
-> MicroAgent
```

Ensure dry-run assertions include:

```python
assert "microagent bundle:" in result.stdout
assert f"agent cwd: {repo_root / 'data' / 'agent-runtime' / 'workspace'}" in result.stdout
assert "agent args: --acp --setting-sources project" in result.stdout
assert "Reference Claude Code" not in result.stdout
```

- [ ] **Step 5: Run the renamed launcher tests and confirm they fail before implementation**

Run:

```bash
rtk proxy .venv/bin/python -m pytest tests/unit/test_microagent_script.py -q
```

Expected before launcher implementation is complete: failures mention missing `scripts/run_microagent.sh` behavior or old path assertions. After Task 3, expected: all tests in this file pass.

---

### Task 6: Update Runtime Setup And ACP Tests

**Files:**
- Modify: `tests/helpers/agent_runtime.py`
- Modify: `tests/unit/agent_runtime/test_setup.py`
- Modify: `tests/unit/api/test_acp_wiring.py`
- Modify if needed: `tests/unit/api/test_providers.py`
- Modify if needed: `tests/conftest.py`
- Modify if needed: `tests/integration/api/test_ui_shell.py`

- [ ] **Step 1: Update the shared test helper**

In `tests/helpers/agent_runtime.py`, ensure `setup_test_agent_runtime()` creates the bundle assets separately from the product workspace:

```python
def setup_test_agent_runtime(tmp_path):
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
```

- [ ] **Step 2: Update setup path default tests**

In `tests/unit/agent_runtime/test_setup.py`, replace the reference-runtime default tests with:

```python
def test_default_agent_runtime_paths_split_microagent_bundle_and_workspace(
    tmp_path: Path,
) -> None:
    paths = default_agent_runtime_paths(tmp_path)
    assert paths.project_root == tmp_path
    assert paths.config_dir == tmp_path / "data" / "agent-runtime" / "config"
    assert paths.workspace_dir == tmp_path / "data" / "agent-runtime" / "workspace"
    assert paths.microagent_dir == tmp_path / "src" / "ragflow_lite" / "microagent"


def test_default_agent_runtime_paths_honor_microagent_dir_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    microagent_dir = tmp_path / "external-microagent"
    monkeypatch.setenv("MICRORAG_MICROAGENT_DIR", str(microagent_dir))

    paths = default_agent_runtime_paths(tmp_path)

    assert paths.microagent_dir == microagent_dir
    assert paths.workspace_dir == tmp_path / "data" / "agent-runtime" / "workspace"
```

- [ ] **Step 3: Update validation tests**

Replace the local settings validation test with:

```python
def test_validate_agent_runtime_workspace_requires_bundle_settings_after_setup(
    tmp_path: Path,
) -> None:
    paths = default_agent_runtime_paths(tmp_path)
    setup_agent_runtime(paths)
    (paths.microagent_dir / ".claude" / "skills").mkdir(parents=True)
    (paths.microagent_dir / ".claude" / "agents").mkdir(parents=True)

    try:
        validate_agent_runtime_workspace(paths)
    except RuntimeError as exc:
        assert str(paths.microagent_dir / ".claude" / "settings.json") in str(exc)
    else:
        raise AssertionError("local MicroAgent settings must be required")
```

Update the success test to write the settings file under `paths.microagent_dir`, not under `paths.workspace_dir`.

- [ ] **Step 4: Update idempotence and migration tests**

Keep tests proving setup does not overwrite product assets, but assert against `paths.workspace_dir`. Add this assertion:

```python
assert not paths.microagent_dir.exists()
```

immediately after `setup_agent_runtime(paths)` in a test that uses a fresh `tmp_path` and does not create the bundle. This confirms setup is not creating or populating the bundle.

- [ ] **Step 5: Update ACP settings default tests**

In `tests/unit/api/test_acp_wiring.py`, replace old default/override tests with:

```python
def test_settings_default_agent_runtime_paths_use_microagent_bundle() -> None:
    settings = Settings.default(Path("/tmp/test-project"))

    assert settings.agent_command == str(
        Path("/tmp/test-project") / "scripts" / "run_microagent.sh"
    )
    assert settings.agent_cwd == str(
        Path("/tmp/test-project") / "data" / "agent-runtime" / "workspace"
    )
    assert settings.agent_config_dir == str(
        Path("/tmp/test-project") / "data" / "agent-runtime" / "config"
    )
    assert settings.microagent_dir == str(
        Path("/tmp/test-project") / "src" / "ragflow_lite" / "microagent"
    )
    assert settings.agent_args == "--acp --setting-sources project"


def test_settings_default_agent_runtime_paths_honor_microagent_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    microagent_dir = tmp_path / "external-microagent"
    monkeypatch.setenv("MICRORAG_MICROAGENT_DIR", str(microagent_dir))

    settings = Settings.default(tmp_path)

    assert settings.microagent_dir == str(microagent_dir)
    assert settings.agent_cwd == str(tmp_path / "data" / "agent-runtime" / "workspace")
```

- [ ] **Step 6: Update `_build_acp_client()` assertions**

Where tests construct `AgentRuntimePaths`, add `microagent_dir=...`. Assert:

```python
assert client._config.cwd == str(paths.workspace_dir)
assert client._config.command == settings.agent_command
assert client._config.args == ["--acp", "--setting-sources", "project"]
```

Do not assert that ACP cwd is the bundle directory.

- [ ] **Step 7: Run focused runtime tests**

Run:

```bash
rtk proxy .venv/bin/python -m pytest \
  tests/unit/agent_runtime/test_setup.py \
  tests/unit/api/test_acp_wiring.py \
  tests/unit/api/test_providers.py \
  -q
```

Expected after Task 4 and this task: all selected tests pass.

---

### Task 7: Update Shared Fixtures, CLI, And UI Shell Test Expectations

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/unit/cli/test_mcrag_cli.py`
- Modify: `tests/integration/api/test_ui_shell.py`

- [ ] **Step 1: Update shared app settings fixture**

In `tests/conftest.py`, update the `Settings(...)` construction in `app_settings()`:

```python
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
        agent_cwd=str(paths.workspace_dir),
        agent_config_dir=str(paths.config_dir),
        microagent_dir=str(paths.microagent_dir),
    )
```

- [ ] **Step 2: Update UI shell settings helper**

In `tests/integration/api/test_ui_shell.py`, update `_ui_test_settings()`:

```python
    settings = Settings(
        project_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        local_index_dir=tmp_path / "local_index",
        temp_dir=tmp_path / "tmp",
        agent_cwd=str(paths.workspace_dir),
        agent_config_dir=str(paths.config_dir),
        microagent_dir=str(paths.microagent_dir),
    )
```

- [ ] **Step 3: Rewrite CLI setup migration assertion**

In `tests/unit/cli/test_mcrag_cli.py`, update the `mcrag agent setup` test so it expects:

```python
def test_agent_setup_command_prepares_product_runtime_paths(
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
        "microagent_dir": str(tmp_path / "src" / "ragflow_lite" / "microagent"),
    }
    assert (tmp_path / "data" / "agent-runtime" / "config").is_dir()
    assert (tmp_path / "data" / "agent-runtime" / "workspace").is_dir()
    assert (tmp_path / "data" / "agent-runtime" / "bin" / "mcrag").is_file()
    assert not (tmp_path / "src" / "ragflow_lite" / "microagent").exists()
```

This locks the boundary that CLI setup does not create the source-tree bundle.

- [ ] **Step 4: Keep UI branding redaction checks intact**

If `tests/integration/api/test_ui_shell.py` has assertions about raw runtime branding, update only the expected old path/name tokens. The test should still reject product-visible text containing:

```python
for forbidden in (
    "Reference Claude Code",
    "reference_claude_code",
    "run_reference_claude_code",
    "参考项目/claude-code",
):
    assert forbidden not in response_text
```

Add `scripts/run_microagent.sh` only if the route intentionally exposes the backend command; otherwise product UI should not surface local paths.

- [ ] **Step 5: Run CLI and UI-adjacent tests**

Run:

```bash
rtk proxy .venv/bin/python -m pytest \
  tests/unit/cli/test_mcrag_cli.py \
  tests/integration/api/test_ui_shell.py \
  -q
```

Expected after code/test updates: all selected tests pass.

---

### Task 8: Update Active Runtime Contracts

**Files:**
- Modify: `src/ragflow_lite/infrastructure/CONTRACTS.md`
- Modify only if product-visible API behavior changes: `src/ragflow_lite/api/CONTRACTS.md`

- [ ] **Step 1: Update infrastructure contract wording**

In `src/ragflow_lite/infrastructure/CONTRACTS.md`, replace the old reference runtime bullet group with:

```markdown
- Settings fields: `agent_command` (env `MICRORAG_AGENT_COMMAND`, default `scripts/run_microagent.sh`), `agent_args` (env `MICRORAG_AGENT_ARGS`, default `"--acp --setting-sources project"`), `agent_cwd` (env `MICRORAG_AGENT_CWD`, default `data/agent-runtime/workspace`), `agent_config_dir` (env `MICRORAG_AGENT_CONFIG_DIR`, default `data/agent-runtime/config`), and `microagent_dir` (env `MICRORAG_MICROAGENT_DIR`, default `src/ragflow_lite/microagent`).
- MicroAgent skills and subagents are bundled runtime assets under `src/ragflow_lite/microagent/.claude/skills` and `src/ragflow_lite/microagent/.claude/agents`.
- The MicroAgent project settings file is `src/ragflow_lite/microagent/.claude/settings.json`; it is copied from the local source runtime, local-only, gitignored, required before agent startup, and not content-inspected during migration.
- Product conversation workspace state remains under `data/agent-runtime/workspace`; `setup_agent_runtime()` prepares workspace/config/shim state and must not create or populate `src/ragflow_lite/microagent`.
- `_build_acp_client(settings)` rejects runtime paths that do not resolve to the project-owned defaults from `default_agent_runtime_paths(settings.project_root)`.
```

- [ ] **Step 2: Leave API contracts unchanged unless tests prove product wording changed**

Run:

```bash
rtk rg -n "Reference Claude Code|reference_claude_code|run_reference_claude_code|参考项目/claude-code" src/ragflow_lite/api tests/integration/api
```

Expected: no product-facing active API contract update is needed if matches are absent or still test-only forbidden-token fixtures.

---

### Task 9: Run Static Verification

**Files:**
- No edits unless verification finds a missed active reference.

- [ ] **Step 1: Check old active names are gone from active runtime files**

Run:

```bash
rtk rg -n "run_reference_claude_code|reference_claude_code|MICRORAG_REFERENCE_CLAUDE_CODE_DIR|Reference Claude Code" scripts src tests
```

Expected: no matches, except intentionally retained historical strings inside redaction tests if the test asserts they are forbidden.

- [ ] **Step 2: Check old active runtime path is gone from active runtime files**

Run:

```bash
rtk rg -n "参考项目/claude-code" scripts src tests
```

Expected: no matches, except intentionally retained redaction fixtures in tests such as `tests/unit/infrastructure/test_agent_activity_projection.py`.

- [ ] **Step 3: Check new env/path references exist**

Run:

```bash
rtk rg -n "MICRORAG_MICROAGENT_DIR|microagent_dir|run_microagent|MicroAgent" scripts src tests
```

Expected: matches appear in the launcher, settings/setup code, tests, and infrastructure contract.

- [ ] **Step 4: Check copied bundle exclusions**

Run:

```bash
rtk proxy find src/ragflow_lite/microagent \( \
  -name .git -o \
  -name .github -o \
  -name node_modules -o \
  -name dist -o \
  -path '*/.claude/settings.local.json' -o \
  -path '*/.claude/.credentials*' -o \
  -path '*/.claude/.cache*' -o \
  -path '*/.claude/cache*' -o \
  -path '*/.claude/history*' -o \
  -path '*/.claude/transcripts*' -o \
  -path '*/.claude/projects*' -o \
  -path '*/.claude/todos*' -o \
  -path '*/.claude/skills/.drafts' \
\) -print
```

Expected: no output.

- [ ] **Step 5: Check settings is ignored**

Run:

```bash
rtk git check-ignore -v src/ragflow_lite/microagent/.claude/settings.json
```

Expected: output points to the `.gitignore` rule added in Task 1.

---

### Task 10: Run Focused Tests And Smoke Checks

**Files:**
- No edits unless tests identify missed implementation work.

- [ ] **Step 1: Run focused pytest suite**

Run:

```bash
rtk proxy .venv/bin/python -m pytest \
  tests/unit/test_microagent_script.py \
  tests/unit/agent_runtime/test_setup.py \
  tests/unit/api/test_acp_wiring.py \
  tests/unit/api/test_providers.py \
  tests/unit/cli/test_mcrag_cli.py \
  tests/integration/api/test_ui_shell.py \
  -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run launcher dry-run**

Run:

```bash
MICRORAG_DEMO_DRY_RUN=1 rtk proxy bash scripts/run_microagent.sh
```

Expected output includes:

```text
microagent bundle: /home/xia/ragflow-lite/src/ragflow_lite/microagent
agent settings: /home/xia/ragflow-lite/src/ragflow_lite/microagent/.claude/settings.json
agent command: /home/xia/ragflow-lite/scripts/run_microagent.sh
agent args: --acp --setting-sources project
agent cwd: /home/xia/ragflow-lite/data/agent-runtime/workspace
```

Expected output does not include:

```text
Reference Claude Code
run_reference_claude_code
参考项目/claude-code
```

- [ ] **Step 3: Verify `mcrag` shim remains usable**

Run:

```bash
rtk proxy command -v mcrag
rtk proxy mcrag --help
```

Expected: `command -v` prints a path and `mcrag --help` exits 0.

- [ ] **Step 4: Run ACP startup smoke only if provider/local env is available**

Run:

```bash
rtk proxy bash scripts/run_microagent.sh --acp --setting-sources project
```

Expected when local env/provider config is available: process starts from the MicroAgent bundle and can enter the ACP flow. If this is not run because provider/local env is unavailable, report it as unverified rather than complete.

---

## Final Report Checklist

- [ ] Report that the bundle was copied first and then pruned/cleaned.
- [ ] Report that `src/ragflow_lite/microagent/.claude/settings.json` was copied, not content-inspected, and is gitignored.
- [ ] Report whether `.claude/skills/.drafts/` was excluded.
- [ ] Report that `vendor/audio-capture-src/` was retained.
- [ ] Report that `progress.md` and upstream README/presentation files were removed or replaced.
- [ ] Report exact focused pytest command results.
- [ ] Report dry-run launcher result.
- [ ] Keep ACP/provider smoke in a separate verified/unverified section.
- [ ] Classify any remaining `Claude Code` / `claude-code` matches as internal runtime source, product-facing fixed, or forbidden test fixture.
