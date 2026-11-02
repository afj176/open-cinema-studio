import hashlib
import io
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import setup


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status, self.headers = status, headers or {}


class SetupTests(unittest.TestCase):
    def item(self, data):
        return {"id":"test", "folder":"vae", "name":"model.safetensors", "bytes":len(data),
                "sha256":hashlib.sha256(data).hexdigest(), "repo":"publisher/model", "path":"model.safetensors"}

    def test_resume_and_verify_before_promotion(self):
        data = b"verified test weights"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "runtime") as folder:
            root = Path(folder)
            (root/"vae").mkdir()
            partial = root/"vae/model.safetensors.part"
            partial.write_bytes(data[:5])
            def opener(req, **kwargs):
                self.assertEqual(req.get_header("Range"), "bytes=5-")
                return Response(data[5:],206,{"Content-Range":f"bytes 5-{len(data)-1}/{len(data)}"})
            setup.install_model(self.item(data),root,lambda *args:None,opener=opener)
            self.assertEqual((root/"vae/model.safetensors").read_bytes(),data)
            self.assertFalse(partial.exists())

    def test_corrupt_file_never_installed_or_overwritten(self):
        data=b"good"
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / "runtime") as folder:
            root=Path(folder)
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                setup.install_model(self.item(data),root,lambda *args:None,opener=lambda *a,**k:Response(b"nope"))
            self.assertFalse((root/"vae/model.safetensors").exists())
            (root/"vae/model.safetensors").write_bytes(b"mine")
            with self.assertRaisesRegex(ValueError,"not overwritten"):
                setup.install_model(self.item(data),root,lambda *args:None)
            self.assertEqual((root/"vae/model.safetensors").read_bytes(),b"mine")

    def test_cross_host_redirect_strips_token(self):
        request=urllib.request.Request("https://huggingface.co/file",headers={"Authorization":"Bearer secret","Range":"bytes=5-"})
        redirected=setup.PublisherRedirect().redirect_request(request,None,302,"found",{},"https://cdn.example/file")
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertEqual(redirected.get_header("Range"),"bytes=5-")

    def test_offline_does_not_enqueue_or_download(self):
        client=type("Client",(),{"server":"http://127.0.0.1:1"})()
        service=setup.Setup(client)
        with patch("setup.urllib.request.urlopen",side_effect=OSError("offline")):
            self.assertFalse(service.status()["ready"])
            with self.assertRaisesRegex(RuntimeError,"offline"):
                service.require("film")
        with self.assertRaisesRegex(ValueError,"models-dir"):
            service.start(["writer"])
        self.assertEqual(service.jobs,{})

    def test_readiness_accepts_core_and_v3_combo_schemas(self):
        import json
        info={n:{} for n in setup.REQUIRED_NODES}
        for item in setup.MANIFEST:
            loader,field=setup.LOADERS[item['folder']]
            fields=info.setdefault(loader,{}).setdefault('input',{}).setdefault('required',{})
            fields.setdefault(field,[[]])[0].append(item['name'])
        loader,field=setup.LOADERS['latent_upscale_models']
        options=info[loader]['input']['required'][field][0]
        info[loader]['input']['required'][field]=['COMBO',{'options':options}]
        service=setup.Setup(type('Client',(),{'server':'http://local'})())
        with patch('setup.urllib.request.urlopen',return_value=Response(json.dumps(info).encode())), patch('setup.shutil.which',return_value='installed'):
            self.assertTrue(service.status()['ready'])
