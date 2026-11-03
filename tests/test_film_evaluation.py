import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from film_evaluation import compare
import benchmark_film_cases


class FilmEvaluationTests(unittest.TestCase):
    def test_different_modes_or_fixture_revisions_are_not_matched(self):
        before = {'case':'one', 'seed':1, 'variant':'old', 'mode':'fast', 'fixture_sha256':'a'}
        after = {**before, 'variant':'new', 'mode':'normal'}
        self.assertEqual(compare([before, after], 'old', 'new')['matched_pairs'], 0)
        after.update(mode='fast', fixture_sha256='b')
        self.assertEqual(compare([before, after], 'old', 'new')['matched_pairs'], 0)
        after.update(fixture_sha256='a', scores={'viewpoint':4, 'audio_quality':3})
        before['scores'] = {'viewpoint':1, 'audio_quality':2}
        report = compare([before, after], 'old', 'new')
        self.assertEqual(report['metrics']['viewpoint']['median_change'], 3)
        self.assertEqual(report['metrics']['audio_quality']['median_change'], 1)

    def test_compares_only_matching_cases_and_never_fills_missing_scores(self):
        records = [
            {'case':'puppet', 'seed':7, 'variant':'old', 'timings':{'first_shot_seconds':100}, 'scores':{'style':2}},
            {'case':'puppet', 'seed':7, 'variant':'new', 'timings':{'first_shot_seconds':60}, 'scores':{'style':4}},
            {'case':'live', 'seed':8, 'variant':'old', 'timings':{'first_shot_seconds':200}},
            {'case':'live', 'seed':8, 'variant':'new', 'timings':{'first_shot_seconds':100}},
            {'case':'cartoon', 'seed':9, 'variant':'new', 'scores':{'style':5}},
        ]
        result = compare(records, 'old', 'new')
        self.assertEqual(result['matched_pairs'], 2)
        self.assertEqual(result['unique_cases'], 2)
        self.assertEqual(result['metrics']['first_shot_seconds']['median_change'], -70)
        self.assertEqual(result['metrics']['style']['pairs'], 1)
        self.assertNotIn('identity', result['metrics'])

    def test_rejects_duplicate_records_and_invalid_scores(self):
        record = {'case':'one', 'seed':1, 'variant':'old'}
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            compare([record, record], 'old', 'new')
        with self.assertRaisesRegex(ValueError, 'between 0 and 5'):
            compare([{'case':'one','seed':1,'variant':'old','scores':{'style':6}},
                     {'case':'one','seed':1,'variant':'new','scores':{'style':3}}], 'old', 'new')

    def test_case_runner_rejects_unsafe_names_and_existing_outputs(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as directory:
            output = Path(directory)
            with self.assertRaisesRegex(ValueError, 'unique simple names'):
                benchmark_film_cases.run([{'id':'../escape'}], output, 'http://localhost:1')
            (output / 'existing').write_text('keep')
            with self.assertRaisesRegex(FileExistsError, 'empty output'):
                benchmark_film_cases.run([{'id':'safe'}], output, 'http://localhost:1')
            self.assertEqual((output / 'existing').read_text(), 'keep')
