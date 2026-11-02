import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from unittest.mock import patch
import launcher
import tempfile


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
        with patch.object(launcher, 'health', return_value={'service':'open-cinema','comfy_url':'http://localhost:8288'}), patch.object(launcher, 'spawn') as spawn:
            self.assertEqual(launcher.ensure_studio('http://localhost:8288'), 'http://127.0.0.1:8420')
            spawn.assert_not_called()

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
