"""MCP stdio server: newline-delimited JSON-RPC 2.0, four methods, no dependencies."""

import json
import sys
import traceback

from . import __version__, client, delegate

PROTOCOL_VERSION = "2025-06-18"

INSTRUCTIONS = (
    "Delegates bounded work to a local MLX model on another Mac, reached privately (for example over Tailscale). "
    "Use mlx_delegate for small, well-specified coding tasks: name the exact files it may write, "
    "the files it should read, and a test command. It works in an isolated git worktree and never "
    "touches the working copy; review the returned diff, then call mlx_apply or mlx_discard. "
    "The local model is slower and weaker than you: keep tasks to one function, file, or test suite, "
    "and review its output like a junior engineer's. Calls can take several minutes."
)

TOOLS = [
    {
        "name": "mlx_status",
        "description": "Check that the model server is reachable and which model it serves.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "mlx_generate",
        "description": "Send one prompt to the local model and return its text. Good for drafts, "
                       "summaries, or boilerplate that you will check. Nothing is written to disk.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The request"},
                "system": {"type": "string", "description": "Optional system instruction"},
                "maxTokens": {"type": "integer", "description": "Default 2048, max 16384"},
                "thinking": {"type": "boolean", "description": "Enable reasoning (much slower). Default false"},
            },
            "required": ["prompt"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "mlx_delegate",
        "description": "Hand one bounded coding task to the local model. It sees only the listed "
                       "files, may write only writeFiles, works in an isolated git worktree from HEAD "
                       "(uncommitted changes are not included; node_modules/.venv are linked from the repo and "
                       "$MLX_WORKER_REPO points at it), runs testCommand there, and retries up to "
                       "maxAttempts with the test output. Returns the diff and test result; applies nothing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Absolute path to the git repository root"},
                "task": {"type": "string", "description": "Precise task: what to change, constraints, acceptance criteria"},
                "writeFiles": {"type": "array", "items": {"type": "string"}, "description": "Repo-relative files the worker may create or change"},
                "readFiles": {"type": "array", "items": {"type": "string"}, "description": "Repo-relative files it should read for context"},
                "testCommand": {"type": "string", "description": "Shell command run in the worktree; must exit 0 to pass"},
                "maxAttempts": {"type": "integer", "description": "1–3, default 2"},
                "testTimeout": {"type": "integer", "description": "Seconds per test run, default 300, max 1800"},
                "thinking": {"type": "boolean", "description": "Enable reasoning (slower). Default false"},
                "maxTokens": {"type": "integer", "description": "Per attempt, default 4096, max 16384"},
                "base": {"type": "string", "description": "Git ref to branch from, default HEAD"},
            },
            "required": ["repo", "task", "writeFiles"],
        },
    },
    {
        "name": "mlx_apply",
        "description": "Apply a delegated task's diff to the repository's working copy (uncommitted) and "
                       "remove its worktree. Refuses if the diff does not apply cleanly.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
    {
        "name": "mlx_discard",
        "description": "Throw away a delegated task's worktree and branch.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
    },
]


def _bounded_tokens(value, default):
    if value is None:
        return default
    if not isinstance(value, int) or not 1 <= value <= 16384:
        raise delegate.DelegateError("maxTokens must be an integer from 1 to 16384")
    return value


def call_tool(name: str, args: dict):
    """Run one tool; raises on bad input or an unreachable model server."""
    if name == "mlx_status":
        return {"url": client.base_url(), "models": client.models()}
    if name == "mlx_generate":
        messages = ([{"role": "system", "content": args["system"]}] if args.get("system") else [])
        messages.append({"role": "user", "content": args["prompt"]})
        reply = client.chat(messages, max_tokens=_bounded_tokens(args.get("maxTokens"), 2048),
                            thinking=bool(args.get("thinking")))
        return {"text": reply["content"], "finishReason": reply["finish_reason"], "usage": reply["usage"]}
    if name == "mlx_delegate":
        return delegate.delegate(
            args["repo"], args["task"], args.get("writeFiles") or [],
            read_files=args.get("readFiles") or [], test_command=args.get("testCommand"),
            max_attempts=args.get("maxAttempts", 2), thinking=bool(args.get("thinking")),
            max_tokens=_bounded_tokens(args.get("maxTokens"), 4096), base=args.get("base", "HEAD"),
            test_timeout=args.get("testTimeout", 300),
        )
    if name == "mlx_apply":
        return delegate.apply(args["id"])
    if name == "mlx_discard":
        return delegate.discard(args["id"])
    raise KeyError(name)


def handle(message: dict):
    """Answer one request; notifications (no id) get no answer."""
    method, msg_id = message.get("method"), message.get("id")
    if "id" not in message:
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "mlx-worker", "version": __version__}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = message.get("params") or {}
        try:
            value = call_tool(params.get("name"), params.get("arguments") or {})
            result = {"content": [{"type": "text", "text": json.dumps(value, indent=2)}],
                      "structuredContent": value, "isError": False}
        except KeyError as error:
            if str(error).strip("'") == params.get("name"):
                return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
            result = {"content": [{"type": "text", "text": f"missing argument {error}"}], "isError": True}
        except (delegate.DelegateError, client.ServerError) as error:
            result = {"content": [{"type": "text", "text": str(error)}], "isError": True}
        except Exception as error:  # a bug should not end the session
            traceback.print_exc(file=sys.stderr)
            result = {"content": [{"type": "text", "text": f"internal error: {error}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"{method} is not supported"}}
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> None:
    try:
        where = client.base_url()
    except client.ServerError as error:
        where = f"not configured ({error})"
    print(f"mlx-worker {__version__}: model server {where}", file=sys.stderr)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            answer = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            answer = handle(message)
        if answer is not None:
            sys.stdout.write(json.dumps(answer) + "\n")
            sys.stdout.flush()
