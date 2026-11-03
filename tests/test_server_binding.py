import socket
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import server


class ServerBindingTests(unittest.TestCase):
    def test_second_server_cannot_bind_same_address(self):
        first = server.StudioHTTPServer(('127.0.0.1', 0), server.Handler)
        try:
            with self.assertRaises(OSError):
                server.StudioHTTPServer(first.server_address, server.Handler)
        finally:
            first.server_close()

    def test_windows_requests_exclusive_binding_without_reuse(self):
        with patch.object(server.os, 'name', 'nt'), \
                patch.object(server.socket, 'SO_EXCLUSIVEADDRUSE', 12345, create=True), \
                patch.object(server.ThreadingHTTPServer, '__init__', return_value=None), \
                patch.object(server.ThreadingHTTPServer, 'server_bind') as bind:
            instance = server.StudioHTTPServer(('127.0.0.1', 0), server.Handler)
            instance.socket = Mock()
            instance.server_bind()
            self.assertFalse(instance.allow_reuse_address)
            instance.socket.setsockopt.assert_called_once_with(socket.SOL_SOCKET, 12345, 1)
            bind.assert_called_once()

    def test_other_platforms_preserve_address_reuse(self):
        with patch.object(server.os, 'name', 'posix'), \
                patch.object(server.ThreadingHTTPServer, '__init__', return_value=None), \
                patch.object(server.ThreadingHTTPServer, 'server_bind') as bind:
            instance = server.StudioHTTPServer(('127.0.0.1', 0), server.Handler)
            instance.socket = Mock()
            instance.server_bind()
            self.assertTrue(instance.allow_reuse_address)
            instance.socket.setsockopt.assert_not_called()
            bind.assert_called_once()


if __name__ == '__main__':
    unittest.main()
