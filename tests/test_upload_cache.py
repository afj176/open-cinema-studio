import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from comfy import Comfy


class UploadCacheTests(unittest.TestCase):
    def test_reuses_identical_content_but_uploads_changed_file(self):
        calls = []
        def open_request(request, **kwargs):
            calls.append(request.get_method())
            return io.BytesIO(json.dumps({'name': 'input.png', 'subfolder': ''}).encode())
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder, patch('urllib.request.urlopen', side_effect=open_request):
            source = Path(folder) / 'image.png'
            source.write_bytes(b'first')
            client = Comfy()
            client.upload(source)
            client.upload(source)
            source.write_bytes(b'other')
            client.upload(source)
        self.assertEqual(calls, ['POST', 'HEAD', 'POST'])

    def test_missing_remote_input_is_uploaded_again(self):
        calls = []
        def open_request(request, **kwargs):
            calls.append(request.get_method())
            if request.get_method() == 'HEAD':
                raise urllib.error.HTTPError(request.full_url, 404, 'missing', {}, None)
            return io.BytesIO(b'{"name":"input.png","subfolder":""}')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder, patch('urllib.request.urlopen', side_effect=open_request):
            source = Path(folder) / 'image.png'
            source.write_bytes(b'first')
            client = Comfy()
            client.upload(source)
            client.upload(source)
        self.assertEqual(calls, ['POST', 'HEAD', 'POST'])

    def test_same_content_reuses_upload_across_display_names(self):
        calls = []
        def open_request(request, **kwargs):
            calls.append(request.get_method())
            return io.BytesIO(b'{"name":"input.png","subfolder":""}')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder, patch('urllib.request.urlopen', side_effect=open_request):
            source = Path(folder) / 'image.png'
            source.write_bytes(b'identical')
            client = Comfy()
            first = client.upload(source, 'portrait.png')
            second = client.upload(source, 'review.png')
        self.assertEqual(first, second)
        self.assertEqual(calls, ['POST', 'HEAD'])

    def test_failed_download_does_not_replace_existing_asset(self):
        class BrokenResponse(io.BytesIO):
            def read(self, size=-1):
                raise OSError('connection lost')
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder, patch('urllib.request.urlopen', return_value=BrokenResponse()):
            target = Path(folder) / 'take.mp4'
            target.write_bytes(b'accepted take')
            with self.assertRaisesRegex(OSError, 'connection lost'):
                Comfy().download({'filename': 'remote.mp4'}, target)
            self.assertEqual(target.read_bytes(), b'accepted take')
            self.assertEqual(list(Path(folder).glob('*.part')), [])

    def test_truncated_download_does_not_promote_partial_asset(self):
        response = io.BytesIO(b'partial')
        response.headers = {'Content-Length': '100'}
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder, patch('urllib.request.urlopen', return_value=response):
            target = Path(folder) / 'take.mp4'
            with self.assertRaisesRegex(RuntimeError, 'declared size'):
                Comfy().download({'filename': 'remote.mp4'}, target)
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(folder).glob('*.part')), [])
