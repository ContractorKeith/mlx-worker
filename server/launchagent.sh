#!/bin/bash
# Run the model server as a per-user launch agent: starts at login, restarts if it exits.
# Usage: server/launchagent.sh install|uninstall|status [--home DIR]
set -euo pipefail

ACTION="${1:-status}"; shift || true
SERVER_HOME="$HOME/mlx-worker-server"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --home) SERVER_HOME="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
LABEL="local.mlx-worker.server"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

case "$ACTION" in
  install)
    [[ -x "$SERVER_HOME/start.sh" ]] || { echo "run server/setup.sh first ($SERVER_HOME/start.sh missing)" >&2; exit 1; }
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$SERVER_HOME/start.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$SERVER_HOME/logs/server.log</string>
  <key>StandardErrorPath</key><string>$SERVER_HOME/logs/server.log</string>
</dict>
</plist>
PLIST
    plutil -lint "$PLIST" >/dev/null
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "installed $PLIST; logs in $SERVER_HOME/logs/server.log"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed $LABEL"
    ;;
  status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state =|pid =|last exit" || echo "$LABEL is not loaded"
    ;;
  *) echo "usage: $0 install|uninstall|status [--home DIR]" >&2; exit 2 ;;
esac
