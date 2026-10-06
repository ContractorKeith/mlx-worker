#!/bin/bash
# Check that this Mac can run an MLX model server. Changes nothing.
# Usage: server/preflight.sh [--port 8080] [--https-port 8443]
set -uo pipefail

PORT=8080
HTTPS_PORT=8443
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --https-port) HTTPS_PORT="$2"; shift 2 ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

fail=0
ok()   { printf '  ok    %s\n' "$1"; }
warn() { printf '  warn  %s\n' "$1"; }
bad()  { printf '  FAIL  %s\n' "$1"; fail=1; }

echo "mlx-worker server preflight"

# Apple Silicon and a recent macOS
[[ "$(uname -m)" == "arm64" ]] && ok "Apple Silicon (arm64)" || bad "not Apple Silicon; MLX needs an M-series Mac"
macos="$(sw_vers -productVersion 2>/dev/null || echo 0)"
if [[ "${macos%%.*}" -ge 15 ]]; then ok "macOS $macos"; elif [[ "${macos%%.*}" -ge 14 ]]; then warn "macOS $macos works; 15+ recommended"; else bad "macOS $macos; MLX needs 14+"; fi

# Memory decides which model fits
mem_gb=$(( $(sysctl -n hw.memsize) / 1073741824 ))
if [[ $mem_gb -ge 48 ]]; then ok "${mem_gb} GB memory (27B-class 4-bit models fit)"
elif [[ $mem_gb -ge 24 ]]; then warn "${mem_gb} GB memory; prefer 14B-class or smaller 4-bit models"
else warn "${mem_gb} GB memory; prefer 8B-class or smaller 4-bit models"; fi

# A native Python 3.11+
py=""
for candidate in python3.13 python3.12 python3.11 python3; do
  path="$(command -v "$candidate" 2>/dev/null)" || continue
  if "$path" -c 'import sys, platform; sys.exit(0 if sys.version_info >= (3, 11) and platform.machine() == "arm64" else 1)' 2>/dev/null; then
    py="$path"; break
  fi
done
[[ -n "$py" ]] && ok "Python: $py ($("$py" --version 2>&1))" || bad "no native arm64 Python 3.11+ found (try: brew install python@3.12)"

# Disk space for a 16 GB-class model plus headroom
free_gb=$(( $(df -k "$HOME" | awk 'NR==2 {print $4}') / 1048576 ))
[[ $free_gb -ge 40 ]] && ok "${free_gb} GB free in \$HOME" || warn "${free_gb} GB free in \$HOME; large models need 20+ GB each"

# The local model port must be free (or already ours)
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  warn "port $PORT is already in use: $(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN | awk 'NR==2 {print $1}')"
else
  ok "port $PORT is free"
fi

# Tailscale for private access
if command -v tailscale >/dev/null 2>&1; then
  if tailscale status >/dev/null 2>&1; then ok "Tailscale is running"; else warn "Tailscale is installed but not running (tailscale up)"; fi
  if tailscale serve status 2>/dev/null | grep -q ":${HTTPS_PORT}"; then
    warn "Tailscale Serve already uses HTTPS port ${HTTPS_PORT}; check before reusing it"
  fi
else
  warn "tailscale CLI not found; install Tailscale for private access from other devices"
fi

[[ $fail -eq 0 ]] && echo "preflight passed" || echo "preflight failed"
exit $fail
