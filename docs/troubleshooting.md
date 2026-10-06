# Troubleshooting

Start on the server: if `curl http://127.0.0.1:8080/v1/models` fails there, nothing else will work.

| Symptom | First check |
|---|---|
| `preflight.sh` finds no Python | Install a native one: `brew install python@3.12`. Rosetta/Intel Python will not work. |
| A public model returns `401` while downloading | A stale Hugging Face login is being sent. `setup.sh` sets `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`; use `hf auth login` only for gated or private models. |
| `Operation not permitted` reading an external drive over SSH | macOS privacy protection blocks SSH sessions from external volumes. Keep models on the internal disk, or run setup from a local Terminal on the server Mac. |
| `serve.sh` says the port already forwards elsewhere | Another Tailscale Serve rule owns that HTTPS port. Pass `--https-port` with a free one; do not overwrite rules you did not create. |
| Laptop gets HTTP 502 | Tailscale reached the server, but the model is not listening. Check `server/launchagent.sh status` and `~/mlx-worker-server/logs/server.log`. |
| Server stops after a reboot | A launch agent starts at login. Log in, or turn on automatic login for a headless server. |
| Thinking request returns no answer | Check `finish_reason`. `length` means the budget ran out mid-reasoning. Make the task smaller or raise `max_tokens`. |
| `mlx_delegate` tests fail with "command not found" or missing modules | The worktree only has tracked files. Dependency folders are linked only if they exist in your repo; for build caches, point the test at `$MLX_WORKER_REPO`. |
| The agent's call times out | Raise the MCP tool timeout (see README). Delegations take minutes. |

On the server, these help:

```bash
lsof -nP -iTCP:8080 -sTCP:LISTEN
server/launchagent.sh status
tail -50 ~/mlx-worker-server/logs/server.log
tailscale serve status
```
