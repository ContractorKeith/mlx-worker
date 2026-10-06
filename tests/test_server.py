"""Tests for mlx_worker.server._bounded_tokens and mlx_worker.server.handle."""

import unittest

from mlx_worker import server, delegate


class TestBoundedTokens(unittest.TestCase):
    def test_none_returns_default(self):
        self.assertEqual(server._bounded_tokens(None, 2048), 2048)

    def test_valid_values_returned_unchanged(self):
        self.assertEqual(server._bounded_tokens(1, 2048), 1)
        self.assertEqual(server._bounded_tokens(16384, 2048), 16384)

    def test_zero_raises(self):
        with self.assertRaises(delegate.DelegateError):
            server._bounded_tokens(0, 2048)

    def test_too_large_raises(self):
        with self.assertRaises(delegate.DelegateError):
            server._bounded_tokens(16385, 2048)

    def test_negative_raises(self):
        with self.assertRaises(delegate.DelegateError):
            server._bounded_tokens(-5, 2048)

    def test_string_raises(self):
        with self.assertRaises(delegate.DelegateError):
            server._bounded_tokens("100", 2048)


class TestHandle(unittest.TestCase):
    def test_no_id_returns_none(self):
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "ping"}))

    def test_ping_returns_empty_result(self):
        response = server.handle({"jsonrpc": "2.0", "id": 7, "method": "ping"})
        self.assertIsInstance(response, dict)
        self.assertEqual(response["result"], {})

    def test_unknown_method_returns_error(self):
        response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "unknown"})
        self.assertIsInstance(response, dict)
        self.assertEqual(response["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main()
