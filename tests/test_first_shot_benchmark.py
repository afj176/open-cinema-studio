"""The scheduler benchmark must not reuse or mutate generated source media."""
import copy
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests'))
import benchmark_first_shot as benchmark
from test_asset_dependencies import fixture


class FirstShotBenchmarkTests(unittest.TestCase):
    def test_preview_completion_only_cancels_this_run_queued_followups(self):
        jobs = [{'project': 'scratch', 'state': 'queued', 'kind': 'review'},
                {'project': 'scratch', 'state': 'queued', 'kind': 'world'},
                {'project': 'scratch', 'state': 'running', 'kind': 'stitch'},
                {'project': 'different', 'state': 'queued', 'kind': 'review'}]
        saves = []
        worker = SimpleNamespace(lock=threading.RLock(), jobs=jobs, _save_jobs=lambda: saves.append(True))
        self.assertEqual(benchmark.finish_after_preview(worker, 'scratch'), 1)
        self.assertEqual([job['state'] for job in jobs], ['cancelled', 'queued', 'running', 'queued'])
        self.assertEqual(saves, [True])

    def test_prepare_copies_planned_first_shot_and_preserves_source(self):
        source, shot = fixture()
        shot['shot_size'] = 'Medium'
        source['continuity_plan']['of'] = benchmark.studio.continuity_inputs(source)
        source['character_references'] = {'Tavi': {'image': 'tavi.png', 'source': 'upload'}}
        original = copy.deepcopy(source)
        result, references = benchmark.prepare(source, 'normal', 77, 99)
        self.assertEqual(source, original)
        self.assertEqual(references, ['portrait.png', 'tavi.png'])
        self.assertEqual(result['ai_mode'], 'normal')
        self.assertEqual(result['shots'][0]['seed'], 77)
        self.assertEqual(result['world'], {'seed': 99, 'takes': [], 'plate': None})
        self.assertIsNone(result['shots'][0]['keyframe'])
        self.assertIsNone(result['shots'][0]['video'])
        self.assertEqual(result['shots'][0]['takes'], {'keyframe': [], 'video': []})
        self.assertEqual(benchmark.studio.plan_status(result), 'ready')

    def test_prepare_rejects_ineligible_and_missing_sources(self):
        source, shot = fixture()
        with self.assertRaisesRegex(ValueError, 'non-wide'):
            benchmark.prepare(source, 'fast', 1, 2)
        shot['shot_size'] = 'Medium'
        source.pop('reference')
        source['continuity_plan']['of'] = benchmark.studio.continuity_inputs(source)
        with self.assertRaisesRegex(ValueError, 'lead portrait'):
            benchmark.prepare(source, 'fast', 1, 2)

    def test_output_cannot_be_inside_source_or_overwrite_existing_data(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'runtime') as directory:
            source_dir = Path(directory) / 'film'
            source_dir.mkdir()
            source = source_dir / 'project.json'
            source.write_text('original', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'outside'):
                benchmark.run(source, source_dir / 'out', 'fast', 'deferred', 1, 2, 'comfy', 'studio', 10, 'unknown')
            output = Path(directory) / 'existing-benchmark-test'
            output.mkdir()
            marker = output / 'marker'
            marker.write_text('keep', encoding='utf-8')
            with patch.object(benchmark, 'studio_is_idle') as idle:
                with self.assertRaisesRegex(ValueError, 'empty'):
                    benchmark.run(source, output, 'fast', 'deferred', 1, 2, 'comfy', 'studio', 10, 'unknown')
                idle.assert_not_called()
            self.assertEqual(marker.read_text(encoding='utf-8'), 'keep')


if __name__ == '__main__':
    unittest.main()
