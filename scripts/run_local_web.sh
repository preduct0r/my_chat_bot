#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${1:-$ROOT_DIR/.env.web.local}"

if [[ $# -eq 0 && ! -f "$ENV_FILE" && -f "$ROOT_DIR/.env" ]]; then
  ENV_FILE="$ROOT_DIR/.env"
fi

if [[ ! -f "$ENV_FILE" ]]; then
  FOUND_ENVS="$(find "$ROOT_DIR" -maxdepth 3 \( -name '.env' -o -name '*.env' \) | sort || true)"
  cat >&2 <<EOF
Missing env file: $ENV_FILE

Create a file with at least:
  OPENAI_API_KEY=...
  OPENAI_MODEL=gpt-4o-mini

Example:
  cp "$ROOT_DIR/.env.example" "$ENV_FILE"
  # then remove TELEGRAM_BOT_TOKEN if you want a web-only local setup
EOF
  if [[ -n "$FOUND_ENVS" ]]; then
    cat >&2 <<EOF

Found env-like files in this repo:
$FOUND_ENVS
EOF
  fi
  exit 1
fi

exec "$ROOT_DIR/.venv/bin/python" -m my_chat_bot.web_main \
  --env-file "$ENV_FILE" \
  --context-size 20 \
  --summary-count 10 \
  --memory-budget 2000 \
  --memory-db-path "$ROOT_DIR/data/local_web.sqlite3" \
  --host 127.0.0.1 \
  --port 8081 \
  --static-dir "$ROOT_DIR/web" \
  --log-level INFO
