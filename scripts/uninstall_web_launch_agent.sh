#!/bin/zsh

set -euo pipefail

PLIST_PATH="$HOME/Library/LaunchAgents/com.den.my-chat-bot-web.plist"
LAUNCHD_DOMAIN="gui/$(id -u)"

launchctl bootout "$LAUNCHD_DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"

echo "Web LaunchAgent removed:"
echo "  $PLIST_PATH"

