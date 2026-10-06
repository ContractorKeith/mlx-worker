# mlx-worker

Public toolkit for running a local MLX model on one Mac and delegating bounded
coding tasks to it from a laptop over MCP. `server/` is the server-Mac kit
(bash, macOS only); `mlx_worker/` is the laptop MCP server (Python standard
library only); `skill/` is an agent-neutral delegation skill.

## Commands

```bash
python3 -m unittest discover -s tests -v       # worker tests (no network, no model)
shellcheck -S warning server/*.sh bin/*         # script lint
MLX_WORKER_URL=https://… ./bin/mlx-worker-mcp   # run the MCP server on stdio
```

## Conventions & Gotchas

- No dependencies in `mlx_worker/`: it must run with the system `python3` (3.9 or newer; tested with 3.14) on macOS and Linux.
- The worker never commits, never writes outside `writeFiles`, and never writes
  outside the repository. Keep those guarantees and their tests.
- Server scripts are re-runnable, never overwrite another Tailscale Serve rule,
  and keep the model server on `127.0.0.1`.
- No personal hostnames, tailnet names, or usernames in this repo. Use
  placeholders like `your-server.your-tailnet.ts.net`.
- Keep `README.md`, `docs/troubleshooting.md`, and the skill in step with tool
  names and options.
