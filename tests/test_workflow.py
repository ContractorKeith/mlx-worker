"""End-to-end delegate/apply/discard against a fake model server (no network, no model)."""

import http.server
import json
import os
import re
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from mlx_worker import delegate


class FakeServer(http.server.BaseHTTPRequestHandler):
    """Answers /v1/models and /v1/chat/completions with a scripted reply."""

    reply_files = {}

    def log_message(self, *args):
        pass

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send({"data": [{"id": "fake-model"}]})

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        tag = re.search(r"copying the tag (\S+) exactly", request["messages"][0]["content"]).group(1)
        blocks = "".join(f"<<<FILE {p} {tag}\n{c}\n>>>END {tag}\n" for p, c in self.reply_files.items())
        self._send({"choices": [{"message": {"content": "Done.\n" + blocks}, "finish_reason": "stop"}],
                    "usage": {"completion_tokens": 5}})


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name).resolve()
        self.repo = base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "app.py").write_text("def add(a, b):\n    return a + b\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "init")
        self.server = http.server.HTTPServer(("127.0.0.1", 0), FakeServer)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.env = {"MLX_WORKER_URL": f"http://127.0.0.1:{self.server.server_port}"}
        os.environ.update(self.env)
        delegate.STATE_ROOT = base / "state"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for key in self.env:
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_only_allowed_files_are_written_and_apply_reaches_the_working_copy(self):
        FakeServer.reply_files = {"test_app.py": "import app\nassert app.add(2, 3) == 5\n",
                                  "app.py": "def add(a, b):\n    return 0\n"}
        result = delegate.delegate(self.repo, "add a test", ["test_app.py"], read_files=["app.py"],
                                   test_command="python3 test_app.py")
        self.assertTrue(result["tests"]["passed"])
        self.assertEqual(result["rejectedFiles"], ["app.py"])
        self.assertIn("+assert app.add(2, 3) == 5", result["diff"])
        self.assertFalse((self.repo / "test_app.py").exists(), "nothing applied before mlx_apply")

        applied = delegate.apply(result["id"])
        self.assertEqual(applied["files"], ["test_app.py"])
        self.assertTrue((self.repo / "test_app.py").exists())
        self.assertIn("return a + b", (self.repo / "app.py").read_text(), "rejected file untouched")
        self.assertFalse((delegate.STATE_ROOT / result["id"]).exists(), "worktree cleaned up")

    def test_dependencies_are_linked_for_tests_but_kept_out_of_the_diff(self):
        (self.repo / ".gitignore").write_text("node_modules/\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "ignore deps")
        (self.repo / "node_modules").mkdir()
        (self.repo / "node_modules" / "dep.txt").write_text("installed")
        FakeServer.reply_files = {"check.sh": "test -f node_modules/dep.txt && test -d \"$MLX_WORKER_REPO\""}
        result = delegate.delegate(self.repo, "add a check", ["check.sh"], test_command="sh check.sh")
        self.assertTrue(result["tests"]["passed"], result["tests"]["outputTail"])
        self.assertEqual(result["linkedDependencies"], ["node_modules"])
        self.assertIn("check.sh", result["diff"])
        self.assertNotIn("b/node_modules", result["diff"], "the linked folder is never staged")
        delegate.discard(result["id"])
        self.assertTrue((self.repo / "node_modules" / "dep.txt").exists(), "discard leaves the repo's deps alone")

    def test_discard_removes_worktree_and_branch(self):
        FakeServer.reply_files = {"notes.txt": "hello"}
        result = delegate.delegate(self.repo, "write notes", ["notes.txt"])
        self.assertTrue(Path(result["worktree"]).exists())
        delegate.discard(result["id"])
        self.assertFalse(Path(result["worktree"]).exists())
        branches = subprocess.run(["git", "-C", str(self.repo), "branch"], capture_output=True, text=True).stdout
        self.assertNotIn(result["branch"], branches)

    def test_paths_outside_the_repo_are_refused_before_any_work(self):
        with self.assertRaises(delegate.DelegateError):
            delegate.delegate(self.repo, "escape", ["../outside.txt"])
        self.assertFalse(delegate.STATE_ROOT.exists(), "no worktree created for a refused task")


if __name__ == "__main__":
    unittest.main()
