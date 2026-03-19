#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

WITH_HTTPS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --with-https)
      WITH_HTTPS=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      echo "Usage: ./scripts/start_stack.sh [--with-https]" >&2
      exit 1
      ;;
  esac
done

mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/data"

"$PROJECT_ROOT/scripts/install_launch_agent.sh"
"$PROJECT_ROOT/scripts/install_web_launch_agent.sh"

echo
echo "Services started:"
echo "  Telegram bot: gui/$(id -u)/com.den.my-chat-bot"
echo "  Web server:   gui/$(id -u)/com.den.my-chat-bot-web"

if [[ "$WITH_HTTPS" -eq 1 ]]; then
  if ! command -v caddy >/dev/null 2>&1; then
    echo
    echo "Caddy is not installed. Install it first, then rerun with --with-https." >&2
    exit 1
  fi

  echo
  echo "Starting Caddy for HTTPS..."
  sudo "$PROJECT_ROOT/scripts/run_caddy_https.sh"
fi

echo
echo "Useful checks:"
echo "  launchctl print gui/$(id -u)/com.den.my-chat-bot"
echo "  launchctl print gui/$(id -u)/com.den.my-chat-bot-web"
echo "  tail -f $PROJECT_ROOT/logs/launchd.stdout.log"
echo "  tail -f $PROJECT_ROOT/logs/web.stdout.log"
