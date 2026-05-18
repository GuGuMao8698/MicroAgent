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
USER_BIN=""
if [[ -n "${HOME:-}" ]]; then
  USER_BIN="$HOME/.local/bin"
fi
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

agent_path_prefix() {
  if [[ -n "$USER_BIN" ]]; then
    printf '%s\n' "$USER_BIN:$RUNTIME_BIN:$ROOT/.venv/bin:$PATH"
  else
    printf '%s\n' "$RUNTIME_BIN:$ROOT/.venv/bin:$PATH"
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
  export PATH="$(agent_path_prefix)"
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
export PATH="$(agent_path_prefix)"

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

if [[ "$MICRORAG_AGENT_ARGS" == *"'"* || "$MICRORAG_AGENT_ARGS" == *'"'* || "$MICRORAG_AGENT_ARGS" == *\\* ]]; then
  die "MICRORAG_AGENT_ARGS only supports whitespace-separated arguments; quotes and escapes are not supported."
fi
read -r -a DEFAULT_AGENT_ARGV <<< "$MICRORAG_AGENT_ARGS"
run_microagent "${DEFAULT_AGENT_ARGV[@]}"
