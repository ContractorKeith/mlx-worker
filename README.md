# mlx-worker

Run a local model on one Mac. Hand it coding tasks from another.

mlx-worker is two small pieces:

- **A server kit** for the Mac with the memory (a Mac Studio, Mac mini, or an old MacBook Pro). It installs [MLX LM](https://github.com/ml-explore/mlx-lm), serves a model on `127.0.0.1`, keeps it running with a launch agent, and shares it privately on your [Tailscale](https://tailscale.com) network.
- **An MCP server** for the laptop you code on. Claude Code, Codex, or any MCP client can hand it one bounded coding task. It sends only the files you name to the model, writes the result into an isolated git worktree, runs your tests there, and returns a diff. Nothing touches your working copy until you apply it. It never commits.

No dependencies on the laptop beyond `python3` and `git`.

```text
LAPTOP                                   SERVER MAC
coding agent (Claude Code, Codex)
  └─ mlx-worker MCP server ── HTTPS over Tailscale ──> Tailscale Serve :8443
       └─ git worktree + your tests                      └─ mlx_lm.server 127.0.0.1:8080
                                                              └─ model (MLX, 4-bit)
```

The full story, with what broke along the way, is in the blog post (link coming).

## What you need

- A server Mac on Apple Silicon, macOS 14 or newer (15+ recommended), with a native Python 3.11+. Memory decides the model: a 27B 4-bit model is about 16 GB and is comfortable on 48 GB or more. On 24 to 32 GB, pick a 14B-class model; on 16 GB, an 8B-class one.
- A laptop with `python3` and `git`. macOS or Linux both work.
- Tailscale on both machines, signed in to the same tailnet.

## 1. Set up the server Mac

```bash
git clone https://github.com/ContractorKeith/mlx-worker.git
cd mlx-worker

server/preflight.sh                 # checks chip, macOS, memory, Python, disk, ports, Tailscale
server/setup.sh                     # venv + MLX LM + config + model download (~16 GB)
server/launchagent.sh install       # start now, at every login, and restart if it exits
server/serve.sh                     # private HTTPS address for your other devices
```

`setup.sh` takes options:

| Option | Default |
|---|---|
| `--model` | `mlx-community/Qwen3.8-27B-4bit` |
| `--home` | `~/mlx-worker-server` (venv, config, logs) |
| `--hf-home` | `~/mlx-worker-server/hf` (model downloads) |
| `--port` | `8080` |
| `--no-download` | download the model during setup |

Browse other sizes on [mlx-community](https://huggingface.co/mlx-community). Re-running setup is safe and skips files already downloaded.

`serve.sh` prints the URL to use on your laptops. It refuses to replace an existing Tailscale Serve rule on the same port; pass `--https-port` to pick another.

Check it on the server:

```bash
curl -sS http://127.0.0.1:8080/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"mlx-community/Qwen3.8-27B-4bit","messages":[{"role":"user","content":"Reply with: ready"}],"max_tokens":10}'
```

A launch agent starts at login. If the server Mac reboots, the model comes back when someone logs in, or at boot if automatic login is on. Keep the Mac from sleeping (System Settings, Energy).

## 2. Connect the laptop

```bash
git clone https://github.com/ContractorKeith/mlx-worker.git ~/mlx-worker
export MLX_WORKER_URL=https://your-server.your-tailnet.ts.net:8443   # from serve.sh
curl -sS "$MLX_WORKER_URL/v1/models"
```

Register the MCP server with your agent, passing the URL:

```bash
# Claude Code
claude mcp add -s user mlx-worker -e MLX_WORKER_URL=https://your-server.your-tailnet.ts.net:8443 \
  -- ~/mlx-worker/bin/mlx-worker-mcp

# Codex
codex mcp add mlx-worker --env MLX_WORKER_URL=https://your-server.your-tailnet.ts.net:8443 \
  -- ~/mlx-worker/bin/mlx-worker-mcp
```

Delegated tasks take minutes. Raise the tool timeout: in Claude Code set `"env": {"MCP_TOOL_TIMEOUT": "1800000"}` in `~/.claude/settings.json`; in Codex add `tool_timeout_sec = 1800` under `[mcp_servers.mlx-worker]` in `~/.codex/config.toml`.

Optionally install the skill in `skill/delegating-to-mlx-worker/` into your agent's skills folder (for example `~/.claude/skills/`). It teaches the agent when to delegate, how to write the brief, and how to review the result.

## The tools

| Tool | What it does |
|---|---|
| `mlx_status` | Checks the server is reachable and lists its model |
| `mlx_generate` | One prompt, returns text. Nothing written to disk |
| `mlx_delegate` | One bounded coding task in an isolated worktree, tested, returned as a diff |
| `mlx_apply` | Applies a task's diff to your working copy, uncommitted |
| `mlx_discard` | Throws a task's worktree and branch away |

How `mlx_delegate` behaves:

- The model sees only `readFiles` and `writeFiles`, and may change only `writeFiles`. Anything else it returns is rejected and listed.
- The worktree branches from `HEAD`, so uncommitted edits are invisible to it.
- `node_modules`, `.venv`, and `venv` are linked from your repo into the worktree and never included in the diff. `$MLX_WORKER_REPO` points at your repo, so a Rust test can reuse its build cache: `CARGO_TARGET_DIR="$MLX_WORKER_REPO/target" cargo test`.
- After a test failure the model gets the output and tries again, up to `maxAttempts` (default 2).
- Thinking is off by default. On a 27B model writing at 18 to 19 tokens a second, thinking on a large task can spend its whole budget reasoning and never answer. Keep tasks small.

## Configuration

| Variable | Where | Purpose |
|---|---|---|
| `MLX_WORKER_URL` | laptop | Server base URL, no trailing `/v1`. Required |
| `MLX_WORKER_MODEL` | laptop | Model ID to request. Default: the first one the server lists |
| `MLX_WORKER_HOME` | laptop | Where task worktrees live. Default `~/.cache/mlx-worker` |

## Security

- The model server binds to `127.0.0.1`. MLX LM warns its built-in server has only basic security checks, so do not expose it directly. Tailscale Serve is the only way in, and only for your tailnet. Do not use Tailscale Funnel for this.
- The code you delegate goes to your own server Mac and nowhere else.
- Test commands run on your laptop, inside the worktree, with your user's permissions. Only run delegations in repos you trust.

## Status

v0.1.0. A personal tool, shared in case it helps. Issues and pull requests are welcome; support is best effort. Tested with MLX 0.32.3, MLX LM 0.32.0, macOS 26.6 on an M2 Max (server) and an M2 MacBook Air (laptop). See [docs/troubleshooting.md](docs/troubleshooting.md).

## License

MIT
