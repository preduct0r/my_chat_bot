#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

"$PROJECT_ROOT/scripts/uninstall_launch_agent.sh"
"$PROJECT_ROOT/scripts/uninstall_web_launch_agent.sh"

echo
echo "Telegram bot and web launch agents stopped."
echo "If Caddy was started manually, stop it separately."
