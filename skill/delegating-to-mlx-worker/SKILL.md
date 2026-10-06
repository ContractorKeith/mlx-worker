---
name: delegating-to-mlx-worker
description: Delegate a small, well-specified, testable coding task to a local MLX model on another Mac through the mlx-worker MCP tools, then review and apply the result. Use when the user asks to use the local model, the server Mac, or a local subagent, or when a single-file task with a clear test would otherwise cost frontier-model tokens.
license: MIT
metadata:
  author: ContractorKeith
  version: 1.0.1
  domain: engineering
  scope: delegation
  output-format: reviewed-diff
---


# Delegating to the MLX worker

The local model on the user's server Mac is a junior engineer on a private
network. A 27B-class 4-bit model on an M2 Max writes about 18-19 tokens a
second but reads prompts at only about 115 tokens a second, so every 1,000 tokens
of `readFiles` adds roughly 9 seconds per attempt. Keep context tight.
You stay the lead: you decide, specify, review, and own the result.

## Decide

- **Delegate:** one function, one file, one test suite, a new self-contained
  file, or boilerplate, with a test command that proves it works.
- **Keep for yourself:** design decisions, concurrency, security, data
  migrations, multi-file refactors, and anything faster to write than to specify.
  For mixed work, write the critical part yourself, commit it through the
  normal flow, then delegate a bounded slice such as its tests. A slice that
  depends on uncommitted work cannot be delegated.
- If the user asks for the local model on work you would keep, say why in one
  sentence, then delegate the largest safe slice instead of refusing.

## Before the call

1. Run `mlx_status`. If it fails, do the work yourself and tell the user the
   model server is down. On the server Mac, `server/launchagent.sh status` shows
   whether it is running, and its log is `~/mlx-worker-server/logs/server.log`.
2. Run `git status`. The worker branches from HEAD and cannot see uncommitted
   edits, so every existing file in `writeFiles` must be clean. Never commit,
   stash, or reset the user's work to get around this. Delegate a new file
   instead and wire it in yourself.
3. Read the target files first so the brief names real functions, helpers, and
   conventions.

## The brief

Pass `repo` as the absolute repository root. `task` states the exact signature or behavior, edge cases with expected values,
what must not change, and the style to match. List every new or existing file it
may change in `writeFiles` and the context it needs in `readFiles`.

**The test command runs in a fresh worktree.** `node_modules`, `.venv`, and
`venv` are linked from the repo, and `$MLX_WORKER_REPO` is the repo's path. Scope the
command to the changed files:

| Stack | testCommand |
|---|---|
| Node | `npx vitest run src/lib/money.test.ts` |
| Rust | `CARGO_TARGET_DIR="$MLX_WORKER_REPO/target" cargo test <name>` with `testTimeout: 900` |
| Python | `python3 -m unittest tests.test_x` |

Keep `thinking` off and `maxTokens` at the default 4096. Use `maxAttempts: 2`.
Turn thinking on only for a small task that needs reasoning, and raise
`maxTokens` with it. A `finishReason` of `length` means the task was too big:
narrow it.

## Review, then apply or discard

- Tests passed, `rejectedFiles` is empty, and only the expected files changed.
- Expected values are correct by hand. Tests do not just restate the code.
  A regression test fails without the fix.
- No new dependencies, stray edits, or placeholder code.

Apply with `mlx_apply`, then run the project's full checks in the real
repo. The worktree ran only the scoped command. If it failed twice, or the
diff is wrong, `mlx_discard` it and do the work yourself. Do not re-send the
same brief.

Tell the user what was delegated, how many attempts it took, and what you
changed after review. Applied changes are uncommitted. Commit them through the
normal flow.
