import hashlib
import io
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import setup


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status, self.headers = status, headers or {}


class SetupTests(unittest.TestCase):
    def test_selected_engine_and_fast_video_exclude_unused_weights(self):
        status = {'connected': True, 'ffmpeg': True,
                  'models': [{**m, 'installed': m['id'] not in ('hidream', 'writer', 'ltx_upscaler')}
                             for m in setup.MANIFEST],
                  'available_nodes': [n for n in setup.REQUIRED_NODES if not n.startswith(('HiDream', 'EmptyHiDream'))]}
        plan = setup.dependency_plan(status, 'film', 'fast', 'klein', 'klein')
        self.assertTrue(plan['ready'])
        self.assertFalse({'hidream', 'writer', 'ltx_upscaler'} & set(plan['model_ids']))
        self.assertIn('qwen_edit', plan['model_ids'])  # ending frames and repairs still use Qwen
        standard = setup.dependency_plan(status, 'film', 'normal', 'klein', 'klein')
        self.assertEqual(set(standard['missing_ids']), {'writer', 'ltx_upscaler'})

    def test_portraits_do_not_require_frame_or_video_models(self):
        ids = {'writer_fast', 'klein', 'klein_te', 'klein_vae'}
        status = {'connected': True, 'ffmpeg': False, 'available_nodes': ['TextGenerate', 'OpenCinemaWriter'],
                  'models': [{**m, 'installed': m['id'] in ids} for m in setup.MANIFEST]}
        for kind in ('cast', 'world', 'character_reference'):
            with self.subTest(kind=kind):
                plan = setup.dependency_plan(status, kind, 'fast', 'klein')
                self.assertTrue(plan['ready'])
                self.assertEqual(set(plan['model_ids']), ids)

    def test_title_motion_and_score_require_only_their_video_models(self):
        self.assertEqual(setup.task_capabilities('title_video', 'fast'), {'video'})
        self.assertEqual(setup.task_capabilities('trailer', 'fast'), {'video', 'video_refine'})
        self.assertIn('hidream', setup.task_capabilities('video'))  # may rebuild its start frame

    def test_workflow_inspection_includes_implicit_writer_and_no_other_engines(self):
        service = setup.Setup(SimpleNamespace(server='http://local'))
        status = {'connected': True, 'model_dir': None, 'downloads': [],
                  'available_nodes': ['OpenCinemaWriter', 'UNETLoader'],
                  'models': [{**m, 'installed': True} for m in setup.MANIFEST]}
        graph = {'1': {'class_type':'OpenCinemaWriter', 'inputs':{'mode':'fast'}},
                 '2': {'class_type':'UNETLoader', 'inputs':{'unet_name':'flux-2-klein-4b.safetensors'}}}
        with patch.object(service, 'status', return_value=status):
            plan = service.workflow_plan(graph)
            self.assertTrue(plan['ready'])
            self.assertEqual({m['id'] for m in plan['models']}, {'writer_fast', 'klein'})
            graph['2']['inputs']['unet_name'] = 'external-model.safetensors'
            plan = service.workflow_plan(graph)
            self.assertFalse(plan['ready'])
            self.assertEqual(plan['unmanaged_models'], ['external-model.safetensors'])
            self.assertFalse(service.workflow_plan({})['ready'])

    def test_workflow_ignores_disconnected_model_loaders(self):
        service = setup.Setup(SimpleNamespace(server='http://local'))
        status = {'connected': True, 'model_dir': None, 'downloads': [],
                  'available_nodes': ['OpenCinemaWriter', 'UNETLoader', 'PreviewAny'], 'output_nodes': ['PreviewAny'],
                  'models': [{**m, 'installed': m['id']=='writer_fast'} for m in setup.MANIFEST]}
        graph = {'1': {'class_type':'OpenCinemaWriter','inputs':{'mode':'fast'}},
                 '2': {'class_type':'UNETLoader','inputs':{'unet_name':'flux-2-klein-4b.safetensors'}},
                 '3': {'class_type':'PreviewAny','inputs':{'source':['1',0]}}}
        with patch.object(service, 'status', return_value=status):
            plan=service.workflow_plan(graph)
            self.assertTrue(plan['ready'])
            self.assertEqual([m['id'] for m in plan['models']], ['writer_fast'])

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

    def test_concurrent_target_creation_never_overwrites_and_keeps_verified_partial(self):
        data = b'publisher model'
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            root = Path(folder)
            target = root / 'vae/model.safetensors'
            def opener(req, **kwargs):
                target.write_bytes(b'user file')  # another process wins after the initial existence check
                return Response(data)
            with self.assertRaisesRegex(ValueError, 'not overwritten'):
                setup.install_model(self.item(data), root, lambda *args: None, opener=opener)
            self.assertEqual(target.read_bytes(), b'user file')
            self.assertEqual(target.with_suffix('.safetensors.part').read_bytes(), data)

    def test_unsupported_atomic_promotion_keeps_partial(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            partial = Path(folder) / 'model.part'
            partial.write_bytes(b'verified')
            target = Path(folder) / 'model'
            with patch('setup.os.link', side_effect=OSError('not supported')):
                with self.assertRaisesRegex(RuntimeError, 'partial was kept'):
                    setup.promote_verified_model(partial, target, windows=False)
            self.assertEqual(partial.read_bytes(), b'verified')
            self.assertFalse(target.exists())

    def test_concurrent_batch_reserves_combined_remaining_bytes(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            root = Path(folder)
            items = [{'folder':'vae', 'name':'one', 'bytes':10}, {'folder':'vae', 'name':'two', 'bytes':10}]
            reserve = 512 * 1024 * 1024
            with patch('setup.shutil.disk_usage', return_value=SimpleNamespace(free=reserve + 15)):
                # Each 10-byte file fits separately, but their simultaneous downloads do not.
                with self.assertRaisesRegex(ValueError, 'selected model downloads'):
                    setup.reserve_download_space(items, root)
                (root / 'vae').mkdir()
                (root / 'vae/one.part').write_bytes(b'1234567')
                setup.reserve_download_space(items, root)  # 3 + 10 bytes remaining

    def test_cross_host_redirect_strips_token(self):
        request=urllib.request.Request("https://huggingface.co/file",headers={"Authorization":"Bearer secret","Range":"bytes=5-"})
        redirected=setup.PublisherRedirect().redirect_request(request,None,302,"found",{},"https://cdn.example/file")
        self.assertIsNone(redirected.get_header("Authorization"))
        self.assertEqual(redirected.get_header("Range"),"bytes=5-")

    def test_downloads_run_concurrently_and_failure_is_isolated(self):
        service = setup.Setup(type('Client', (), {'server': 'http://local'})(), Path.cwd())
        items = [{'id':'one', 'bytes':1}, {'id':'two', 'bytes':1}]
        service.jobs = {item['id']: {'state':'queued', 'done':0} for item in items}
        barrier = threading.Barrier(2)
        def install(item, root, progress, token):
            barrier.wait(timeout=2)
            if item['id'] == 'one':
                raise ValueError('bad checksum')
            progress('downloading', 1)
        with patch('setup.install_model', side_effect=install):
            service._install(items)
        self.assertEqual(service.jobs['one']['state'], 'failed')
        self.assertEqual(service.jobs['two']['state'], 'installed')

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
        info.update({node:{} for nodes in setup.WRITING_NODES.values() for node in nodes})
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

    def test_story_writing_does_not_require_image_video_nodes_or_weights(self):
        import json
        info = {name:{} for name in setup.WRITING_NODES['write_story']}
        loader, field = setup.LOADERS['text_encoders']
        info.setdefault(loader, {}).setdefault('input', {}).setdefault('required', {})[field] = [[
            item['name'] for item in setup.MANIFEST if item['group'] in ('writing','writing_fast')]]
        service = setup.Setup(type('Client',(),{'server':'http://local'})())
        with patch('setup.urllib.request.urlopen', return_value=Response(json.dumps(info).encode())), patch('setup.shutil.which',return_value=None):
            status = service.status()
            self.assertTrue(status['modes']['normal']['ready'])
            self.assertFalse(status['modes']['normal']['film_ready'])
            service.require('write_story', target='everything', mode='normal')
            with self.assertRaisesRegex(RuntimeError, 'nodes are missing|Models are missing'):
                service.require('film', mode='normal')

    def test_opt_in_klein_frame_requires_its_assets_in_both_modes(self):
        service = setup.Setup(type('Client',(),{'server':'http://local'})())
        models = [{**item, 'installed': item['group'] != 'images_fast'} for item in setup.MANIFEST]
        status = {'connected':True,'missing_nodes':[],'missing_fast_image_nodes':[],'models':models,'ffmpeg':True}
        with patch.object(service, 'status', return_value=status):
            for mode in ('normal','fast'):
                service.require('write_story', target='everything', mode=mode, frame_backend='klein')
                with self.assertRaisesRegex(RuntimeError, 'flux-2-klein-4b'):
                    service.require('film', mode=mode, frame_backend='klein')

    def test_klein_frame_nodes_do_not_block_klein_text_to_image(self):
        service = setup.Setup(SimpleNamespace(server='http://local'))
        status = {'connected': True, 'missing_nodes': [], 'missing_fast_image_nodes': [],
                  'missing_klein_frame_nodes': ['ReferenceLatent'],
                  'models': [{**item, 'installed': True} for item in setup.MANIFEST], 'ffmpeg': True}
        with patch.object(service, 'status', return_value=status):
            service.require('world', image_backend='klein')
            with self.assertRaisesRegex(RuntimeError, 'ReferenceLatent'):
                service.require('keyframe', frame_backend='klein')

    def test_scanned_roots_require_all_categories(self):
        spec = importlib.util.spec_from_file_location('test_bridge', Path(__file__).resolve().parents[1] / 'custom_nodes/comfyui-open-cinema/studio_bridge.py')
        bridge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bridge)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            root, partial = Path(folder) / 'all', Path(folder) / 'partial'
            root.mkdir(); partial.mkdir()
            paths = {category: [str(root / category), str(partial / category)] for category in bridge.MODEL_CATEGORIES}
            paths['vae'] = [str(root / 'vae')]
            fake = SimpleNamespace(get_folder_paths=lambda category: paths[category])
            self.assertEqual(bridge.scanned_model_roots(fake), [setup.os.path.normcase(str(root.resolve()))])

    def test_root_selection_is_advertised_persistent_and_cannot_change_during_download(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            root = Path(folder) / 'models'; root.mkdir()
            pref = Path(folder) / 'preferences.json'
            client = SimpleNamespace(server='http://127.0.0.1:8188')
            service = setup.Setup(client, preferences_path=pref)
            response = Response(json.dumps({'roots': [str(root), str(root / 'missing')]}).encode())
            with patch('setup.urllib.request.urlopen', return_value=response):
                roots = service.model_roots()
            self.assertEqual(len(roots), 1)
            with patch.object(service, 'model_roots', return_value=roots), patch.object(service, 'status', return_value={}):
                with self.assertRaisesRegex(ValueError, 'no longer available'):
                    service.select_model_root(str(root))
                service.select_model_root(roots[0]['id'])
                self.assertEqual(service.model_dir, root.resolve())
                service.jobs['model'] = {'state': 'downloading'}
                with self.assertRaisesRegex(ValueError, 'finish'):
                    service.select_model_root(roots[0]['id'])
            restored = setup.Setup(client, preferences_path=pref)
            self.assertEqual(restored._saved_model_dir(roots), root.resolve())
            self.assertIsNone(restored._saved_model_dir([]))
            self.assertIsNone(setup.Setup(SimpleNamespace(server='http://127.0.0.1:9999'), preferences_path=pref)._saved_model_dir(roots))
            explicit = setup.Setup(client, model_dir=Path(folder), preferences_path=pref)
            with self.assertRaisesRegex(ValueError, 'launcher or environment'):
                explicit.select_model_root(roots[0]['id'])
            self.assertEqual(explicit.model_dir, Path(folder).resolve())

    def test_remote_comfy_never_discloses_or_selects_local_roots(self):
        service = setup.Setup(SimpleNamespace(server='http://remote.example:8188'))
        with patch('setup.urllib.request.urlopen') as request:
            self.assertEqual(service.model_roots(), [])
            request.assert_not_called()
