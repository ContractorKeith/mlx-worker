"""Unit tests for mlx_worker.delegate (parse_files and _inside)."""

import tempfile
import unittest
from pathlib import Path

from mlx_worker import delegate

OPEN_MARKER = '<<<' + 'FILE '
CLOSE_MARKER = '>>>END '


def block(path, contents, tag):
    """Build one FILE block without ever containing a literal marker line."""
    return f"{OPEN_MARKER}{path} {tag}\n{contents}\n{CLOSE_MARKER}{tag}"


class ParseFilesTest(unittest.TestCase):
    def test_two_tagged_blocks(self):
        tag = "T12345678"
        text = (
            "Here is a summary.\n\n"
            + block("a.txt", "alpha\nbeta", tag)
            + "\n\n"
            + block("b.txt", "gamma", tag)
            + "\n"
        )
        files = delegate.parse_files(text, tag)
        self.assertEqual(files, {"a.txt": "alpha\nbeta\n", "b.txt": "gamma\n"})

    def test_contents_with_untagged_end_line_are_not_cut_short(self):
        tag = "T12345678"
        # The body contains an untagged >>>END line that must not terminate the
        # tagged block early.
        contents = "first\n" + CLOSE_MARKER + "no-tag\nlast"
        text = "preamble\n\n" + block("a.txt", contents, tag) + "\n"
        files = delegate.parse_files(text, tag)
        self.assertEqual(files, {"a.txt": contents + "\n"})

    def test_exact_untagged_end_line_does_not_end_a_tagged_block(self):
        # The original bug: a parser's own tests contain a bare >>>END line.
        tag = "T12345678"
        contents = "x = 1\n" + CLOSE_MARKER.strip() + "\ny = 2"
        text = block("t.py", contents, tag)
        self.assertEqual(delegate.parse_files(text, tag), {"t.py": contents + "\n"})

    def test_no_blocks_returns_empty_dict(self):
        self.assertEqual(delegate.parse_files("no blocks here at all\n"), {})


class InsideTest(unittest.TestCase):
    def test_inside_returns_path_within_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            result = delegate._inside(root, "a/b.txt")
            self.assertEqual(result, (root / "a" / "b.txt").resolve())
            self.assertIn(root, result.parents)

    def test_escape_raises_delegate_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with self.assertRaises(delegate.DelegateError):
                delegate._inside(root, "../escape.txt")


if __name__ == "__main__":
    unittest.main()
