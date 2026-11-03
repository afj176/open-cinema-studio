import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from unittest.mock import patch
import launcher
import server
import tempfile
import os


class LauncherTests(unittest.TestCase):
    def test_environment_layouts_and_spaces(self):
        with tempfile.TemporaryDirectory(dir=launcher.ROOT) as folder:
            root = Path(folder) / 'Comfy UI'
            root.mkdir()
            for windows, relative in [(False, '.venv/bin/python'), (True, '.venv/Scripts/python.exe')]:
                candidate = root / relative
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.touch()
                self.assertEqual(launcher.discover_python(root, windows=windows), candidate)
            explicit = root / 'custom python'
            explicit.touch()
            self.assertEqual(launcher.discover_python(root, str(explicit)), explicit)

    def test_explicit_comfy_path_validation(self):
        with tempfile.TemporaryDirectory(dir=launcher.ROOT) as folder:
            root = Path(folder)
            with self.assertRaisesRegex(RuntimeError, 'main.py'):
                launcher.discover_comfy(root)
            (root / 'main.py').touch()
            self.assertEqual(launcher.discover_comfy(root), root.resolve())

    def test_missing_python_has_actionable_error(self):
        with tempfile.TemporaryDirectory(dir=launcher.ROOT) as folder, patch.dict(launcher.os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'comfy-python'):
                launcher.discover_python(Path(folder), windows=False)

    def test_reuses_matching_studio(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(launcher, 'health', return_value={'service':'open-cinema','comfy_url':'http://localhost:8288'}), patch.object(launcher, 'spawn') as spawn:
            self.assertEqual(launcher.ensure_studio('http://localhost:8288'), 'http://127.0.0.1:8420')
            spawn.assert_not_called()

    def test_models_dir_is_forwarded_to_studio_and_companion_environment(self):
        with tempfile.TemporaryDirectory(dir=launcher.ROOT) as folder, patch.dict(os.environ, {'OPEN_CINEMA_MODELS_DIR': folder}, clear=True), \
                patch.object(launcher, 'health', return_value=None), patch.object(launcher, 'spawn') as spawn, \
                patch.object(launcher, 'wait_ready', return_value={'service':'open-cinema','comfy_url':'http://localhost:8288',
                                                                  'model_dir':str(Path(folder).resolve())}):
            launcher.ensure_studio('http://localhost:8288')
            command = spawn.call_args.args[0]
            self.assertEqual(command[command.index('--models-dir') + 1], str(Path(folder).resolve()))

    def test_cli_models_dir_propagates_before_starting_comfy(self):
        with tempfile.TemporaryDirectory(dir=launcher.ROOT) as folder, patch.dict(os.environ, {}, clear=True), \
                patch.object(sys, 'argv', ['launcher.py', '--models-dir', folder, '--no-browser']), \
                patch.object(launcher, 'health', return_value={'ready': True}), \
                patch.object(launcher, 'ensure_studio', return_value='http://127.0.0.1:8420') as ensure:
            launcher.main()
            expected = str(Path(folder).resolve())
            self.assertEqual(os.environ['OPEN_CINEMA_MODELS_DIR'], expected)
            ensure.assert_called_once_with('http://127.0.0.1:8288', 8420, expected)

    def test_reuse_rejects_a_different_or_unconfigured_model_dir(self):
        with tempfile.TemporaryDirectory(dir=launcher.ROOT) as folder, patch.dict(os.environ, {}, clear=True), \
                patch.object(launcher, 'health', return_value={'service':'open-cinema','comfy_url':'http://localhost:8288'}), \
                patch.object(launcher, 'spawn') as spawn:
            with self.assertRaisesRegex(RuntimeError, 'different model download folder'):
                launcher.ensure_studio('http://localhost:8288', models_dir=folder)
            spawn.assert_not_called()

    def test_startup_race_does_not_reuse_a_server_with_different_models_dir(self):
        with tempfile.TemporaryDirectory(dir=launcher.ROOT) as folder, patch.dict(os.environ, {}, clear=True), \
                patch.object(launcher, 'health', return_value=None), patch.object(launcher, 'spawn'), \
                patch.object(launcher, 'wait_ready', return_value={'service':'open-cinema','comfy_url':'http://localhost:8288',
                                                                  'model_dir':None}):
            with self.assertRaisesRegex(RuntimeError, 'different model download folder'):
                launcher.ensure_studio('http://localhost:8288', models_dir=folder)

    def test_matching_configured_model_dir_reuses_running_studio(self):
        with tempfile.TemporaryDirectory(dir=launcher.ROOT) as folder, patch.dict(os.environ, {}, clear=True), \
                patch.object(launcher, 'health', return_value={'service':'open-cinema','comfy_url':'http://localhost:8288',
                                                               'model_dir':str(Path(folder).resolve())}), \
                patch.object(launcher, 'spawn') as spawn:
            self.assertEqual(launcher.ensure_studio('http://localhost:8288', models_dir=folder), 'http://127.0.0.1:8420')
            spawn.assert_not_called()

    def test_direct_studio_start_honors_model_dir_environment(self):
        with tempfile.TemporaryDirectory(dir=launcher.ROOT) as folder, \
                patch.dict(os.environ, {'OPEN_CINEMA_MODELS_DIR': folder}, clear=True), \
                patch.object(sys, 'argv', ['server.py']), \
                patch.object(server, 'StudioHTTPServer') as http, \
                patch.object(server, 'Studio') as studio, patch.object(server, 'Setup') as setup, \
                patch.object(server.Handler, 'studio', create=True):
            server.main()
            setup.assert_called_once_with(studio.return_value.comfy, folder)
            http.return_value.serve_forever.assert_called_once()

    def test_different_backend_is_not_silently_reused(self):
        with patch.object(launcher, 'health', return_value={'service':'open-cinema','comfy_url':'http://localhost:8188'}):
            with self.assertRaisesRegex(RuntimeError, 'different ComfyUI'):
                launcher.ensure_studio('http://localhost:8288')

    def test_failed_child_surfaces_immediately(self):
        class Failed:
            returncode = 1
            def poll(self): return 1
        with patch.object(launcher, 'health', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'Service exited'):
                launcher.wait_ready('http://localhost:1', Failed())
