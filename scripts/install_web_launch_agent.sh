#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/com.den.my-chat-bot-web.plist"
TEMPLATE_PATH="$PROJECT_ROOT/launchd/com.den.my-chat-bot-web.plist.template"
LAUNCHD_DOMAIN="gui/$(id -u)"

mkdir -p "$LAUNCH_AGENTS_DIR" "$PROJECT_ROOT/logs" "$PROJECT_ROOT/data"

export PROJECT_ROOT
export TEMPLATE_PATH
export PLIST_PATH
python3 - <<'PY'
import os
from pathlib import Path

project_root = os.environ["PROJECT_ROOT"]
template_path = Path(os.environ["TEMPLATE_PATH"])
plist_path = Path(os.environ["PLIST_PATH"])
contents = template_path.read_text(encoding="utf-8")
contents = contents.replace("${PROJECT_ROOT}", project_root)
plist_path.write_text(contents, encoding="utf-8")
PY

launchctl bootout "$LAUNCHD_DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "$LAUNCHD_DOMAIN" "$PLIST_PATH"
launchctl enable "$LAUNCHD_DOMAIN/com.den.my-chat-bot-web"
launchctl kickstart -k "$LAUNCHD_DOMAIN/com.den.my-chat-bot-web"

echo "Web LaunchAgent installed:"
echo "  $PLIST_PATH"

