"""Run one bounded coding task on the local model inside an isolated git worktree.

The model only sees the files the caller names, writes only the files it
is allowed to change, and never touches the caller's working copy. Results stay
in a worktree until the caller applies or discards them. Nothing is committed.
"""

import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from . import client

STATE_ROOT = Path(os.environ.get("MLX_WORKER_HOME", Path.home() / ".cache" / "mlx-worker"))
MAX_FILE_CHARS = 40_000      # per file sent to the model
MAX_CONTEXT_CHARS = 120_000  # all files sent to the model
MAX_DIFF_CHARS = 30_000      # diff returned to the caller
OUTPUT_TAIL_CHARS = 4_000    # test output returned to the caller
MAX_TEST_TIMEOUT = 1_800     # seconds
# Ignored dependency folders a fresh worktree lacks; linked from the repo so tests
# can run without reinstalling, and always kept out of the diff.
LINKED_DEPENDENCY_DIRS = ("node_modules", ".venv", "venv")

# Each task gets a random tag in its FILE markers, so file contents that mention
# the marker format (a parser's own tests, docs) cannot end a block early.
SYSTEM_PROMPT = """You are a careful software engineer working on one bounded task.
Change only the files you are allowed to write. Return every changed or new file
IN FULL using exactly this format, one block per file, copying the tag {tag} exactly:

<<<FILE relative/path/from/repo/root {tag}
complete file contents
>>>END {tag}

Before the blocks you may write at most three sentences of summary. Write nothing
after the last block. Never use the block format for files you did not change."""


def _block_pattern(tag):
    """FILE-block regex; with a tag, only markers carrying that exact tag count."""
    if tag:
        t = re.escape(tag)
        return re.compile(rf"<<<FILE (?P<path>[^\n]+?) {t}\n(?P<body>.*?)\n?>>>END {t}", re.DOTALL)
    return re.compile(r"<<<FILE (?P<path>[^\n]+)\n(?P<body>.*?)\n?>>>END", re.DOTALL)


class DelegateError(Exception):
    """The task could not be set up or its result could not be used."""


def _git(repo, *args, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise DelegateError(f"git {' '.join(args)} failed: {result.stderr.strip()[:300]}")
    return result.stdout


def _inside(root: Path, relative: str) -> Path:
    """Resolve a repo-relative path, refusing anything that escapes the repo."""
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise DelegateError(f"path escapes the repository: {relative}")
    return candidate


def parse_files(text: str, tag: str = None) -> dict:
    """Extract {path: contents} from the model's FILE blocks (tagged when tag is given)."""
    return {match["path"].strip(): match["body"] + "\n" for match in _block_pattern(tag).finditer(text)}


def _context(root: Path, paths: list) -> str:
    parts, total = [], 0
    for relative in paths:
        path = _inside(root, relative)
        if not path.is_file():
            parts.append(f"--- {relative} (does not exist yet)\n")
            continue
        text = path.read_text(errors="replace")
        if len(text) > MAX_FILE_CHARS:
            raise DelegateError(f"{relative} is larger than {MAX_FILE_CHARS} characters; narrow the task")
        total += len(text)
        if total > MAX_CONTEXT_CHARS:
            raise DelegateError(f"selected files exceed {MAX_CONTEXT_CHARS} characters; narrow the task")
        parts.append(f"--- {relative}\n{text}\n")
    return "".join(parts)


def _link_dependencies(root: Path, worktree: Path) -> list:
    """Symlink the repo's existing dependency folders into the worktree."""
    linked = []
    for name in LINKED_DEPENDENCY_DIRS:
        source, target = root / name, worktree / name
        if source.is_dir() and not target.exists():
            target.symlink_to(source, target_is_directory=True)
            linked.append(name)
    return linked


def _stage(worktree: Path, linked: list) -> None:
    """Stage the worker's changes, never the linked dependency folders."""
    excludes = [f":(exclude){name}" for name in linked]
    _git(worktree, "add", "-A", "--", ".", *excludes)


def _run_tests(worktree: Path, command: str, timeout: int, repo: Path) -> dict:
    # MLX_WORKER_REPO lets a command reuse the original checkout's caches, e.g.
    # CARGO_TARGET_DIR="$MLX_WORKER_REPO/target" cargo test
    env = {**os.environ, "MLX_WORKER_REPO": str(repo)}
    try:
        result = subprocess.run(command, shell=True, cwd=worktree, capture_output=True, text=True,
                                timeout=timeout, env=env)
        output = (result.stdout + result.stderr)[-OUTPUT_TAIL_CHARS:]
        return {"passed": result.returncode == 0, "exitCode": result.returncode, "outputTail": output}
    except subprocess.TimeoutExpired:
        return {"passed": False, "exitCode": None, "outputTail": f"test command timed out after {timeout}s"}


def delegate(repo, task, write_files, read_files=(), test_command=None, max_attempts=2,
             thinking=False, max_tokens=4096, test_timeout=300, base="HEAD") -> dict:
    """Create a worktree, ask the model for the change, write it, and test it."""
    root = Path(repo).expanduser().resolve()
    if not (root / ".git").exists():
        raise DelegateError(f"{root} is not the root of a git repository")
    if not write_files:
        raise DelegateError("writeFiles must name at least one file the worker may change")
    if not 1 <= max_attempts <= 3:
        raise DelegateError("maxAttempts must be 1–3")
    if not 1 <= test_timeout <= MAX_TEST_TIMEOUT:
        raise DelegateError(f"testTimeout must be 1–{MAX_TEST_TIMEOUT} seconds")
    allowed = {str(Path(p)) for p in write_files}
    for relative in list(write_files) + list(read_files):
        _inside(root, relative)

    task_id = uuid.uuid4().hex[:10]
    tag = "T" + uuid.uuid4().hex[:8]
    home = STATE_ROOT / task_id
    worktree = home / "worktree"
    branch = f"mlx-worker/{task_id}"
    home.mkdir(parents=True)
    _git(root, "worktree", "add", "-q", "-b", branch, str(worktree), base)
    linked = _link_dependencies(root, worktree)
    meta = {"id": task_id, "repo": str(root), "worktree": str(worktree), "branch": branch, "task": task,
            "linked": linked}
    (home / "meta.json").write_text(json.dumps(meta, indent=2))

    wt = worktree.resolve()
    context = _context(wt, list(dict.fromkeys(list(read_files) + list(write_files))))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(tag=tag)},
        {"role": "user", "content": (
            f"Task:\n{task}\n\nFiles you may write: {', '.join(sorted(allowed))}\n"
            + (f"Test command that must pass: {test_command}\n" if test_command else "")
            + f"\nCurrent files:\n{context}"
        )},
    ]

    attempts, tests, summary, rejected = [], None, "", []
    for attempt in range(1, max_attempts + 1):
        reply = client.chat(messages, max_tokens=max_tokens, thinking=thinking)
        files = parse_files(reply["content"], tag)
        record = {"attempt": attempt, "finishReason": reply["finish_reason"],
                  "completionTokens": reply["usage"].get("completion_tokens"), "filesWritten": []}
        if not files:
            record["error"] = "the model returned no FILE blocks"
            attempts.append(record)
            messages += [{"role": "assistant", "content": reply["content"]},
                         {"role": "user", "content": f"You returned no FILE blocks. Return the changed files in the required format with the tag {tag}."}]
            continue
        summary = reply["content"].split("<<<FILE", 1)[0].strip()[:600]
        for relative, body in files.items():
            if str(Path(relative)) not in allowed:
                rejected.append(relative)
                continue
            target = _inside(wt, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)
            record["filesWritten"].append(relative)
        attempts.append(record)
        if not test_command:
            break
        tests = _run_tests(wt, test_command, test_timeout, root)
        record["testsPassed"] = tests["passed"]
        if tests["passed"]:
            break
        messages += [{"role": "assistant", "content": reply["content"]},
                     {"role": "user", "content": (
                         f"The test command failed (exit {tests['exitCode']}). Output tail:\n"
                         f"{tests['outputTail']}\n\nFix the files and return them in full again.")}]

    _stage(wt, linked)
    diff = _git(wt, "diff", "--cached", "HEAD")
    meta["diffChars"] = len(diff)
    (home / "meta.json").write_text(json.dumps(meta, indent=2))
    return {
        "id": task_id,
        "worktree": str(worktree),
        "branch": branch,
        "summary": summary,
        "attempts": attempts,
        "tests": tests,
        "rejectedFiles": rejected,
        "linkedDependencies": linked,
        "diff": diff[:MAX_DIFF_CHARS] + ("\n… diff truncated" if len(diff) > MAX_DIFF_CHARS else ""),
        "note": "Nothing was applied to your working copy. Review the diff, then call mlx_apply or mlx_discard.",
    }


def _load(task_id: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{10}", task_id or ""):
        raise DelegateError("unknown task id")
    meta_path = STATE_ROOT / task_id / "meta.json"
    if not meta_path.is_file():
        raise DelegateError(f"no delegated task {task_id}")
    return json.loads(meta_path.read_text())


def discard(task_id: str) -> dict:
    """Remove the task's worktree and branch."""
    meta = _load(task_id)
    _git(meta["repo"], "worktree", "remove", "--force", meta["worktree"], check=False)
    _git(meta["repo"], "branch", "-D", meta["branch"], check=False)
    shutil.rmtree(STATE_ROOT / task_id, ignore_errors=True)
    return {"id": task_id, "discarded": True}


def apply(task_id: str) -> dict:
    """Apply the task's diff to the caller's working copy (uncommitted), then clean up."""
    meta = _load(task_id)
    diff = _git(meta["worktree"], "diff", "--cached", "HEAD")
    if not diff.strip():
        raise DelegateError("the task produced no changes")
    check = subprocess.run(["git", "-C", meta["repo"], "apply", "--check", "-"], input=diff, capture_output=True, text=True)
    if check.returncode != 0:
        raise DelegateError(f"the diff does not apply cleanly: {check.stderr.strip()[:300]}")
    subprocess.run(["git", "-C", meta["repo"], "apply", "-"], input=diff, capture_output=True, text=True, check=True)
    changed = [line[6:] for line in diff.splitlines() if line.startswith("+++ b/")]
    discard(task_id)
    return {"id": task_id, "applied": True, "files": changed, "note": "Changes are uncommitted in your working copy."}
