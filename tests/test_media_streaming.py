import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from server import Handler


class MediaStreamingTests(unittest.TestCase):
    def serve(self, path, range_header=''):
        handler = object.__new__(Handler)
        handler.headers = {'Range': range_header}
        handler.wfile = io.BytesIO()
        headers = {}
        status = []
        handler.send_response = status.append
        handler.send_header = headers.__setitem__
        handler.end_headers = lambda: None
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('whole-file read')):
            handler._file(path)
        return status[0], headers, handler.wfile.getvalue()

    def test_ranges_stream_only_requested_bytes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            path = Path(folder) / 'clip.mp4'
            path.write_bytes(b'0123456789')
            for request, expected in [('bytes=2-4', b'234'), ('bytes=-3', b'789'),
                                      ('bytes=8-99', b'89'), ('bytes=0-', b'0123456789')]:
                status, headers, body = self.serve(path, request)
                self.assertEqual(status, 206)
                self.assertEqual(body, expected)
                self.assertEqual(int(headers['Content-Length']), len(expected))
            status, headers, body = self.serve(path, 'bytes=99-')
            self.assertEqual((status, body), (416, b''))
            self.assertEqual(headers['Content-Range'], 'bytes */10')
            self.assertEqual(self.serve(path)[2], b'0123456789')
