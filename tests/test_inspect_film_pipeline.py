"""The scratch inspection tool must retain evidence without inventing quality scores."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('film_inspection', ROOT / 'tools' / 'inspect_film_pipeline.py')
inspection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inspection)


class FilmInspectionTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        folder = root / 'projects' / 'abc1'
        folder.mkdir(parents=True)
        shots = [{'id':'shot1', 'video':'shot.mp4', 'keyframe':'frame.png',
                  'line':'Lead: "Hello."', 'action':'The lead waves', 'start_frame':'The lead faces the camera'}]
        project = {'id':'abc1', 'film':None, 'shots':shots,
                   'evaluation':{'case':'sample', 'fixture_sha256':'abc'}}
        report = {'project_id':'abc1', 'film':None, 'shots':shots}
        (folder / 'project.json').write_text(json.dumps(project), encoding='utf-8')
        report_path = root / 'report.json'
        report_path.write_text(json.dumps(report), encoding='utf-8')
        return root, folder, report_path

    def test_stale_report_and_outside_media_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'runtime') as directory:
            root, folder, report_path = self.fixture(directory)
            data = json.loads(report_path.read_text(encoding='utf-8'))
            data['shots'][0]['video'] = 'older.mp4'
            report_path.write_text(json.dumps(data), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Selected takes changed'):
                inspection.load_evaluation(report_path)
            (root / 'outside.mp4').write_bytes(b'private')
            with self.assertRaisesRegex(ValueError, 'outside'):
                inspection.media_file(folder, '../../outside.mp4')

    def test_inspection_does_not_write_inside_project_or_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'runtime') as directory:
            root, folder, report_path = self.fixture(directory)
            (folder / 'shot.mp4').write_bytes(b'existing')
            with self.assertRaisesRegex(ValueError, 'outside'):
                inspection.inspect(report_path, folder / 'new')
            output = root / 'existing'
            output.mkdir()
            (output / 'keep.txt').write_text('keep', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'empty output'):
                inspection.inspect(report_path, output)
            self.assertEqual((output / 'keep.txt').read_text(encoding='utf-8'), 'keep')

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and FFprobe required')
    def test_real_clip_creates_unscored_evidence_without_modifying_project(self):
        try:
            import PIL  # noqa: F401
        except ImportError:
            self.skipTest('Pillow required')
        with tempfile.TemporaryDirectory(dir=ROOT / 'runtime') as directory:
            root, folder, report_path = self.fixture(directory)
            source = folder / 'shot.mp4'
            subprocess.run([shutil.which('ffmpeg'), '-nostdin', '-v', 'error', '-f', 'lavfi',
                            '-i', 'color=c=red:s=64x64:r=10:d=1', '-f', 'lavfi',
                            '-i', 'sine=frequency=440:duration=1', '-c:v', 'mpeg4', '-c:a', 'aac',
                            '-shortest', str(source)], check=True, timeout=30)
            before = (folder / 'project.json').read_bytes()
            with patch.dict('os.environ', {'OPEN_CINEMA_WHISPER_MODEL': ''}):
                result = inspection.inspect(report_path, root / 'inspection', speech_enabled=True)
            self.assertEqual((folder / 'project.json').read_bytes(), before)
            self.assertTrue((root / 'inspection/contact-sheet.png').is_file())
            self.assertEqual(result['shots'][0]['speech_observation']['status'], 'unavailable')
            self.assertTrue(result['shots'][0]['audio_stream'])
            self.assertIsNotNone(result['shots'][0]['mean_audio_db'])
            self.assertEqual(result['shots'][0]['scripted_dialogue'], 'Lead: "Hello."')
            self.assertTrue(all(item['status'] == 'not_assessed' for item in result['manual_review'].values()))


if __name__ == '__main__':
    unittest.main()
