#!/bin/bash
# Start mlx_lm.server on 127.0.0.1 with the settings from env.sh next to this script.
set -euo pipefail

HOME_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$HOME_DIR/env.sh"
# Serve only the downloaded model; never reach Hugging Face at startup.
export HF_HUB_OFFLINE=1

# Loopback only: other devices reach it through Tailscale Serve, never directly.
exec "$HOME_DIR/venv/bin/mlx_lm.server" \
  --model "$MLX_MODEL" \
  --host 127.0.0.1 \
  --port "${MLX_PORT:-8080}" \
  --allowed-origins "" \
  --decode-concurrency 1 \
  --prompt-concurrency 1 \
  --prompt-cache-size 1 \
  --chat-template-args '{"enable_thinking":false}' \
  --temp 0.7 \
  --top-p 0.8 \
  --top-k 20 \
  --max-tokens 2048
