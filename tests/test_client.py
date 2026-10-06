"""The client refuses to guess a server address."""

import os
import unittest
from unittest import mock

from mlx_worker import client


class BaseUrlTest(unittest.TestCase):
    def test_missing_url_is_a_clear_error(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(client.ServerError) as raised:
                client.base_url()
        self.assertIn("MLX_WORKER_URL", str(raised.exception))

    def test_trailing_slash_is_removed(self):
        with mock.patch.dict(os.environ, {"MLX_WORKER_URL": "https://example.ts.net:8443/"}):
            self.assertEqual(client.base_url(), "https://example.ts.net:8443")


if __name__ == "__main__":
    unittest.main()
