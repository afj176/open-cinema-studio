"""Timing summaries do not infer film runs or treat missing observations as zero."""
from pathlib import Path
import copy
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from performance_report import report


class PerformanceReportTests(unittest.TestCase):
    def test_distinguishes_queue_execution_and_paired_end_to_end_without_inventing_values(self):
        jobs = [
            {'project':'x', 'kind':'video', 'state':'done', 'ai_mode':'fast', 'elapsed':20,
             'timing':{'queue_seconds':100, 'upload_seconds':1, 'download_seconds':3}},
            {'project':'x', 'kind':'video', 'state':'done', 'ai_mode':'fast', 'elapsed':10, 'timing':{}},
            {'project':'x', 'kind':'video', 'state':'done', 'ai_mode':'fast',
             'timing':{'queue_seconds':50, 'wait_seconds':2}},
        ]
        original = copy.deepcopy(jobs)
        text = report(jobs)
        self.assertIn('median execution | median queue | median queue + execution', text)
        self.assertIn('15.0s (2/3) | 75.0s (2/3) | 120.0s (1/3) | 2.0s (1/3) | 4.0s (1/3)', text)
        self.assertIn('missing instrumentation is not counted as zero', text)
        self.assertEqual(jobs, original)

    def test_missing_and_invalid_timings_are_not_reported_as_zero(self):
        jobs = [{'kind':'video', 'state':'done', 'elapsed':None,
                 'timing':{'queue_seconds':float('nan'), 'wait_seconds':-1}}]
        text = report(jobs)
        self.assertIn('n/a | n/a | n/a | n/a | n/a', text)
        self.assertNotIn('0.0s', text)

    def test_first_playable_uses_earliest_selected_clip_for_each_explicit_run(self):
        jobs = [
            {'project':'film1', 'kind':'video', 'state':'done', 'ai_mode':'fast', 'render_started_at':100,
             'timing':{'playable_at':145, 'observed_nodes':{'Sampler':{'seconds':8, 'spans':1}}}},
            {'project':'film1', 'kind':'video', 'state':'done', 'ai_mode':'fast', 'render_started_at':100,
             'timing':{'playable_at':135}},
            {'project':'film1', 'kind':'video', 'state':'done', 'ai_mode':'fast', 'timing':{'queue_seconds':9}},
            {'project':'film2', 'kind':'video', 'state':'done', 'ai_mode':'fast', 'render_started_at':100,
             'timing':{'playable_at':101}},
        ]
        text = report(jobs, project='film1')
        self.assertIn('film1 / 1970-01-01 00:01:40 | 35.0s', text)
        self.assertNotIn('film2', text)
        self.assertIn('Sampler | 8.0s | 1', text)
        self.assertIn('partial event-stream observations', text)

    def test_legacy_or_invalid_timestamps_do_not_invent_first_playable(self):
        jobs = [{'project':'x', 'kind':'video', 'state':'done', 'timing':{}},
                {'project':'x', 'kind':'video', 'state':'done', 'render_started_at':float('nan'),
                 'timing':{'playable_at':3}},
                {'project':'x', 'kind':'video', 'state':'done', 'render_started_at':5,
                 'timing':{'playable_at':3}}]
        self.assertNotIn('first selected playable shot', report(jobs))


if __name__ == '__main__':
    unittest.main()
