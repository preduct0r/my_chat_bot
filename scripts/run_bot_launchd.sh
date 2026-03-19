#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/data"

export UV_CACHE_DIR="${UV_CACHE_DIR:-$PROJECT_ROOT/.uv-cache}"

exec uv run my-chat-bot \
  --context-size "${BOT_CONTEXT_SIZE:-10}" \
  --summary-count "${BOT_SUMMARY_COUNT:-3}" \
  --memory-budget "${BOT_MEMORY_BUDGET:-1200}" \
  --session-timeout-seconds "${BOT_SESSION_TIMEOUT_SECONDS:-3600}" \
  --memory-db-path "${BOT_MEMORY_DB_PATH:-$PROJECT_ROOT/data/bot_memory.sqlite3}" \
  --env-file "${BOT_ENV_FILE:-$PROJECT_ROOT/.env}" \
  --poll-timeout "${BOT_POLL_TIMEOUT:-30}" \
  --log-level "${BOT_LOG_LEVEL:-INFO}"

