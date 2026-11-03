"""Safety checks for resuming scratch GPU benchmarks."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pipeline_benchmark', ROOT / 'tools' / 'benchmark_film_pipeline.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class PipelineBenchmarkSafetyTests(unittest.TestCase):
    def test_scripted_cases_are_distinct_repeatable_and_override_is_recorded(self):
        cases = ROOT / 'tests' / 'fixtures' / 'film_pipeline_cases.json'
        first = benchmark.load_case(cases, 'live_action_keys')
        self.assertEqual(first['fixture_sha256'], benchmark.load_case(cases, 'live_action_keys')['fixture_sha256'])
        alternate = benchmark.load_case(cases, 'live_action_keys', 'From behind Asha, facing Emil')
        self.assertNotEqual(first['fixture_sha256'], alternate['fixture_sha256'])
        self.assertEqual(alternate['shots'][1]['start_frame'], 'From behind Asha, facing Emil')
        self.assertNotEqual(first['look'], benchmark.load_case(cases, 'stop_motion_parcel')['look'])
        self.assertTrue(all(shot.get('line') for shot in first['shots']))
        self.assertEqual(first['shots'][1]['frame_source'], 'previous_end')
        second_seed = benchmark.load_case(cases, 'live_action_keys', seed_offset=100)
        self.assertEqual([s['seed'] for s in second_seed['shots']],
                         [(s['seed'] + 100) % (2**31) for s in first['shots']])
        self.assertNotEqual(first['fixture_sha256'], second_seed['fixture_sha256'])
        self.assertEqual(second_seed['fixture_sha256'], benchmark.load_case(cases, 'live_action_keys', seed_offset=100)['fixture_sha256'])
        with self.assertRaisesRegex(ValueError, 'unique'):
            benchmark.load_case(cases, 'missing')

    def test_resume_rejects_non_scratch_identifier_and_preserves_report(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'runtime') as directory:
            output = Path(directory)
            report = output / 'report.json'
            original = json.dumps({'project_id': '../outside'})
            report.write_text(original, encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'valid scratch project ID'):
                benchmark.resume(output, 'http://127.0.0.1:8288', 'http://127.0.0.1:8420', 30)
            self.assertEqual(report.read_text(encoding='utf-8'), original)
            self.assertFalse((output / 'report-resumed.json').exists())

    def test_resume_never_starts_worker_when_shared_studio_is_busy(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'runtime') as directory:
            output = Path(directory)
            (output / 'report.json').write_text(json.dumps({'project_id': 'scratch1'}), encoding='utf-8')
            project = output / 'projects' / 'scratch1' / 'project.json'
            project.parent.mkdir(parents=True)
            project.write_text('{"id":"scratch1"}', encoding='utf-8')
            with patch.object(benchmark, 'studio_is_idle', return_value=False), \
                 patch.object(benchmark.studio, 'Studio') as worker:
                with self.assertRaisesRegex(RuntimeError, 'active jobs'):
                    benchmark.resume(output, 'http://127.0.0.1:8288', 'http://127.0.0.1:8420', 30)
            worker.assert_not_called()
            self.assertEqual(project.read_text(encoding='utf-8'), '{"id":"scratch1"}')


if __name__ == '__main__':
    unittest.main()
