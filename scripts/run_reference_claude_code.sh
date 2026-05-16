#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REFERENCE_CLAUDE_CODE_DIR="${MICRORAG_REFERENCE_CLAUDE_CODE_DIR:-$ROOT/参考项目/claude-code}"

die() {
  echo "setup error: $*" >&2
  exit 2
}

if ! command -v bun >/dev/null 2>&1; then
  die "bun command not found in PATH"
fi

if [[ ! -d "$REFERENCE_CLAUDE_CODE_DIR" ]]; then
  die "missing reference Claude Code project: $REFERENCE_CLAUDE_CODE_DIR"
fi

if [[ ! -d "$REFERENCE_CLAUDE_CODE_DIR/node_modules" ]]; then
  echo "setup error: missing $REFERENCE_CLAUDE_CODE_DIR/node_modules" >&2
  echo "Run: cd \"$REFERENCE_CLAUDE_CODE_DIR\" && bun install" >&2
  exit 2
fi

run_reference_claude_code() {
  cd "$REFERENCE_CLAUDE_CODE_DIR"
  export CLAUDE_CONFIG_DIR="${CLAUDE_CONFIG_DIR:-$ROOT/data/agent-runtime/config}"
  export MICRORAG_AGENT_CWD="${MICRORAG_AGENT_CWD:-$ROOT/data/agent-runtime/workspace}"
  export MICRORAG_AGENT_CONFIG_DIR="${MICRORAG_AGENT_CONFIG_DIR:-$ROOT/data/agent-runtime/config}"
  require_local_settings
  exec bun --silent run dev -- "$@"
}

require_local_settings() {
  local settings_path="$ROOT/data/agent-runtime/workspace/.claude/settings.json"
  if [[ ! -f "$settings_path" ]]; then
    echo "setup error: missing $settings_path" >&2
    echo "Create this local-only file with your Claude Code permissions before starting MicroRAG agent runtime." >&2
    exit 2
  fi
}

if (($# > 0)); then
  run_reference_claude_code "$@"
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  die "missing $ROOT/.venv/bin/python"
fi

LOCAL_ENV="$ROOT/data/agent-runtime/local.env"
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

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

HOST="${MICRORAG_HOST:-127.0.0.1}"
PORT="${MICRORAG_PORT:-8001}"

export CLAUDE_CONFIG_DIR="$ROOT/data/agent-runtime/config"
export MICRORAG_AGENT_CWD="$ROOT/data/agent-runtime/workspace"
export MICRORAG_AGENT_CONFIG_DIR="$ROOT/data/agent-runtime/config"
export MICRORAG_AGENT_COMMAND="${MICRORAG_AGENT_COMMAND:-$ROOT/scripts/run_reference_claude_code.sh}"
export MICRORAG_AGENT_ARGS="${MICRORAG_AGENT_ARGS:---acp --setting-sources project}"

if [[ "${MICRORAG_DEMO_DRY_RUN:-}" == "1" ]]; then
  echo "agent setup: $ROOT/.venv/bin/python -m ragflow_lite.cli.mcrag agent setup --project-root $ROOT"
  echo "agent settings: $MICRORAG_AGENT_CWD/.claude/settings.json"
  echo "backend: $ROOT/.venv/bin/python -m uvicorn ragflow_lite.app:app --host $HOST --port $PORT --reload"
  echo "ui: http://$HOST:$PORT/agent"
  echo "agent command: $MICRORAG_AGENT_COMMAND"
  echo "agent args: $MICRORAG_AGENT_ARGS"
  echo "agent cwd: $MICRORAG_AGENT_CWD"
  echo "agent config: $CLAUDE_CONFIG_DIR"
  exit 0
fi

"$ROOT/.venv/bin/python" -m ragflow_lite.cli.mcrag agent setup --project-root "$ROOT" >/dev/null
require_local_settings

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
echo "Reference Claude Code: $REFERENCE_CLAUDE_CODE_DIR"
echo "Agent command: $MICRORAG_AGENT_COMMAND"
echo "Agent args: $MICRORAG_AGENT_ARGS"
echo "Agent cwd: $MICRORAG_AGENT_CWD"
echo "Agent config: $CLAUDE_CONFIG_DIR"
echo "Agent settings: $MICRORAG_AGENT_CWD/.claude/settings.json"
echo "Use /status in Claude Code to verify settings sources."

cd "$REFERENCE_CLAUDE_CODE_DIR"
exec bun --silent run dev -- --setting-sources project
