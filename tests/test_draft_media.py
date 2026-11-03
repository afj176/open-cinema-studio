"""Small real-FFmpeg checks for draft and review-reel output, without model inference."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import studio
from test_asset_dependencies import fixture


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg and FFprobe are optional integration dependencies')
class DraftMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='draft media ', dir=studio.ROOT)
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.folder = Path(cls.temporary.name)
        for name, color, frequency in [('clip one.mp4', 'navy', '440'), ('clip two.mp4', 'darkgreen', '660')]:
            subprocess.run([shutil.which('ffmpeg'), '-y', '-loglevel', 'error',
                            '-f', 'lavfi', '-i', f'color=c={color}:s=640x352:r=24:d=0.5',
                            '-f', 'lavfi', '-i', f'sine=frequency={frequency}:sample_rate=48000:duration=0.5',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
                            '-c:a', 'aac', '-shortest', str(cls.folder / name)],
                           check=True, capture_output=True, timeout=15)

    def harness(self):
        project, first = fixture()
        project.update(review_policy='draft', finish=False)
        first['video'] = 'clip one.mp4'
        second = copy.deepcopy(first)
        second.update(id='second', video='clip two.mp4')
        project['shots'].append(second)
        for index, shot in enumerate(project['shots']):
            shot['takes']['keyframe'][0]['review'] = {
                'version': studio.director.REVIEW_VERSION, 'status': 'passed', 'outcome': 'passed', 'findings': []}
            shot['takes']['video'][0].update(name=shot['video'], review={
                'version': studio.director.REVIEW_VERSION,
                'status': 'needs_review' if index == 0 else 'passed',
                'outcome': 'uncertain' if index == 0 else 'passed',
                'findings': ['Foreground action needs inspection'] if index == 0 else []})
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.path = lambda _: self.folder
        worker.load = lambda _: project
        worker.save = Mock(side_effect=lambda fresh: fresh)
        worker._dress = Mock(side_effect=lambda _project, clips, _job, _tick: clips)
        worker._credits = Mock(return_value=None)
        return worker, project

    def probe(self, path):
        result = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-show_streams',
                                 '-show_format', '-of', 'json', str(path)],
                                check=True, capture_output=True, text=True, timeout=10)
        return json.loads(result.stdout)

    def bottom_frame(self, path):
        return subprocess.run([shutil.which('ffmpeg'), '-v', 'error', '-i', str(path),
                               '-vf', 'crop=iw:48:0:ih-48,format=gray', '-frames:v', '1',
                               '-f', 'rawvideo', '-'], check=True, capture_output=True, timeout=10).stdout

    def test_draft_is_playable_watermarked_and_keeps_findings(self):
        worker, project = self.harness()
        clips = [self.folder / shot['video'] for shot in project['shots']]
        for name, draft in [('clean cut.mp4', False), ('draft cut.mp4', True)]:
            worker._assemble(project, clips, name, 640, 352, {'project': project['id']},
                             lambda _: None, preset='ultrafast', draft=draft)
        clean, draft = self.folder / 'clean cut.mp4', self.folder / 'draft cut.mp4'
        info = self.probe(draft)
        self.assertEqual({stream['codec_type'] for stream in info['streams']}, {'video', 'audio'})
        self.assertGreater(float(info['format']['duration']), 0.9)
        baseline, marked = self.bottom_frame(clean), self.bottom_frame(draft)
        self.assertEqual(len(baseline), 640 * 48)
        self.assertGreater(sum(abs(a-b) for a, b in zip(baseline, marked)) / len(baseline), 1)
        self.assertEqual(studio.current_take(project['shots'][0], 'video')['review']['status'], 'needs_review')

    def test_review_reel_contains_only_flagged_current_clips_with_audio(self):
        worker, project = self.harness()
        project['film'] = 'existing draft.mp4'
        project['film_of'] = studio.film_inputs(project)
        original = copy.deepcopy(studio.current_take(project['shots'][0], 'video')['review'])
        worker._run_review_reel({'project': project['id']}, lambda _: None)
        reel = self.folder / project['review_reel']
        info = self.probe(reel)
        self.assertEqual({stream['codec_type'] for stream in info['streams']}, {'video', 'audio'})
        self.assertGreater(float(info['format']['duration']), 0.4)
        self.assertLess(float(info['format']['duration']), 0.8)
        self.assertEqual(project['review_reel_of'], project['film'])
        self.assertEqual(studio.current_take(project['shots'][0], 'video')['review'], original)
        self.assertEqual(studio.film_review(project)['status'], 'draft')
