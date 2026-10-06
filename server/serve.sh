#!/bin/bash
# Share the local model server privately on your tailnet with Tailscale Serve.
# Usage: server/serve.sh [--port 8080] [--https-port 8443] [--off]
set -euo pipefail

PORT=8080
HTTPS_PORT=8443
OFF=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --https-port) HTTPS_PORT="$2"; shift 2 ;;
    --off) OFF=1; shift ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
command -v tailscale >/dev/null || { echo "tailscale CLI not found" >&2; exit 1; }

if [[ $OFF -eq 1 ]]; then
  tailscale serve --bg --https="$HTTPS_PORT" off
  exit 0
fi

# Never replace someone else's rule on this HTTPS port.
target="http://127.0.0.1:$PORT"
existing="$(tailscale serve status --json 2>/dev/null | /usr/bin/python3 -c '
import json, sys
port = sys.argv[1]
data = json.load(sys.stdin) if sys.stdin.readable() else {}
for host, web in (data.get("Web") or {}).items():
    if host.endswith(":" + port):
        for handler in (web.get("Handlers") or {}).values():
            print(handler.get("Proxy", "other"))
' "$HTTPS_PORT" 2>/dev/null || true)"
if [[ -n "$existing" && "$existing" != "$target" ]]; then
  echo "HTTPS port $HTTPS_PORT already forwards to $existing; pick another with --https-port" >&2
  exit 1
fi
if [[ -z "$existing" ]]; then
  tailscale serve --bg --https="$HTTPS_PORT" "$target"
fi

name="$(tailscale status --json | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo "private URL for your other devices: https://$name:$HTTPS_PORT"
echo "set on each laptop:  export MLX_WORKER_URL=https://$name:$HTTPS_PORT"
