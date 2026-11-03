import json
from pathlib import Path
import sys
import unittest
import copy
import importlib.util
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'custom_nodes/comfyui-open-cinema'))
import director
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import studio

node_path = Path(__file__).resolve().parents[1] / 'custom_nodes/comfyui-open-cinema/__init__.py'
node_spec = importlib.util.spec_from_file_location('open_cinema_review_nodes', node_path,
                                                   submodule_search_locations=[str(node_path.parent)])
review_nodes = importlib.util.module_from_spec(node_spec)
sys.modules[node_spec.name] = review_nodes
node_spec.loader.exec_module(review_nodes)


class ReviewContractTests(unittest.TestCase):
    def test_malformed_observation_reaches_parser_without_fabricated_evidence(self):
        raw = '{"count": 1, "style" "pass"}'
        result, = review_nodes.OpenCinemaAppendObservation().append(
            text=[raw], key=['Cup · held by'], observation=['A teen holds the cup'])
        self.assertEqual(result, raw)
        review = director.parse_visual_review(result, self.expected(), state_audit=self.audit())
        self.assertEqual(review['outcome'], 'reviewer_error')
        self.assertEqual(review['raw'], raw)

    def test_observations_are_added_to_valid_review(self):
        raw = json.dumps(self.report())
        result, = review_nodes.OpenCinemaAppendObservation().append(
            text=[raw], key=['Cup · held by'], observation=['  A teen holds the cup  '])
        self.assertEqual(json.loads(result)['state'], [
            {'key': 'Cup · held by', 'verdict': 'observed', 'observed': 'A teen holds the cup'}])

    def expected(self):
        return json.dumps({'state': {'Cup · held by': 'Avery'}, 'count': 1,
                           'people': {'Avery': 'a teen with a purple jacket and short black hair'}})

    def report(self):
        return {'count': 1, 'style': {'verdict': 'pass', 'observed': 'Flat cel-painted drawing'},
                'cast': {'verdict': 'pass', 'observed': 'One teen in a purple jacket'},
                'state': [{'key': 'Cup · held by', 'verdict': 'observed', 'observed': 'Purple-jacketed teen holds the cup'}]}

    def audit(self, verdict='pass', reason='The observed teen matches the holder description'):
        return json.dumps({'state': [{'key': 'Cup · held by', 'verdict': verdict, 'reason': reason}]})

    def parse(self, report=None, audit=None):
        return director.parse_visual_review(json.dumps(report or self.report()), self.expected(),
                                            state_audit=audit if audit is not None else self.audit())

    def test_confirmed_failure_uncertainty_and_schema_errors_are_distinct(self):
        good = self.parse()
        self.assertEqual((good['status'], good['outcome'], good['issues']), ('passed', 'passed', []))
        mismatch = self.parse(audit=self.audit('fail', 'The cup rests unattended on the table'))
        self.assertEqual(mismatch['outcome'], 'content_issue')
        self.assertEqual(mismatch['issues'][0]['severity'], 'blocking')
        uncertain = self.parse(audit=self.audit('uncertain', 'The holder is outside the crop'))
        self.assertEqual(uncertain['outcome'], 'uncertain')
        self.assertEqual(uncertain['issues'][0]['category'], 'uncertain')
        malformed = self.parse(audit='{"state":[]}')
        self.assertEqual(malformed['outcome'], 'reviewer_error')
        self.assertFalse(any(i['category'] == 'content_issue' for i in malformed['issues']))
        self.assertEqual(malformed['state_audit_raw'], '{"state":[]}')

    def test_broken_audit_preserves_separately_confirmed_cast_failure(self):
        report = self.report()
        report['count'] = 2
        result = self.parse(report, '{}')
        self.assertEqual(result['outcome'], 'reviewer_error')
        self.assertEqual([issue['category'] for issue in result['issues']], ['content_issue', 'reviewer_error'])

    def test_invalid_verdict_is_a_reviewer_error(self):
        result = self.parse(audit=self.audit('yes'))
        self.assertEqual(result['outcome'], 'reviewer_error')

    def test_explicitly_inconclusive_reason_is_neither_pass_nor_confirmed_defect(self):
        for result in ('pass', 'fail'):
            review = self.parse(audit=self.audit(result, 'Insufficient evidence; cannot determine who holds the cup.'))
            self.assertEqual(review['outcome'], 'uncertain')
            self.assertEqual(review['evidence']['state_comparison'][0]['verdict'], result)
            self.assertEqual(review['evidence']['state_comparison'][0]['interpreted_verdict'], 'uncertain')

    def test_uncalibrated_material_finding_cannot_trigger_automatic_pixel_repair(self):
        key = 'Avery · rendering material'
        expected = json.dumps({'state': {key:'photographed human'}, 'count':1, 'advisory_facts':[key]})
        report = self.report()
        report['state'] = [{'key':key, 'verdict':'observed', 'observed':'A textured figure'}]
        audit = json.dumps({'state':[{'key':key, 'verdict':'fail', 'reason':'The observer describes molded wood.'}]})
        result = director.parse_visual_review(json.dumps(report), expected, state_audit=audit)
        self.assertEqual(result['outcome'], 'uncertain')
        self.assertFalse(any(issue['category'] == 'content_issue' for issue in result['issues']))
        result = self.parse(audit=self.audit('pass', 'The holder does not match the required person'))
        self.assertEqual(result['outcome'], 'reviewer_error')

    def test_audit_key_whitespace_is_trimmed_but_different_keys_are_not_guessed(self):
        audit = {'state': [{'key': '  Cup · held by ', 'verdict': 'uncertain',
                            'reason': 'The holder is not visible'}]}
        result = self.parse(audit=json.dumps(audit))
        self.assertEqual(result['outcome'], 'uncertain')
        self.assertEqual(result['evidence']['state_comparison'][0]['key'], 'Cup · held by')
        audit['state'][0]['key'] = 'cup · held by'
        self.assertEqual(self.parse(audit=json.dumps(audit))['outcome'], 'reviewer_error')

    def test_audit_keys_that_collide_after_trimming_are_rejected(self):
        expected = json.dumps({'state': {'Cup · held by': 'Avery', 'Door · position': 'open'},
                               'count': 1, 'people': {'Avery': 'purple jacket'}})
        report = self.report()
        report['state'].append({'key': 'Door · position', 'verdict': 'observed', 'observed': 'The door is open'})
        audit = {'state': [{'key': 'Cup · held by', 'verdict': 'pass', 'reason': 'Avery holds it'},
                           {'key': ' Cup · held by ', 'verdict': 'pass', 'reason': 'Avery holds it'}]}
        result = director.parse_visual_review(json.dumps(report), expected, state_audit=json.dumps(audit))
        self.assertEqual(result['outcome'], 'reviewer_error')
        self.assertIn('does not cover', result['findings'][-1])

    def test_uncountable_cast_is_uncertain_not_confirmed_extra_actor(self):
        report = self.report()
        report['count'] = None
        result = self.parse(report)
        self.assertEqual(result['outcome'], 'uncertain')
        self.assertEqual(result['issues'][0]['code'], 'cast_count_unverifiable')

    def test_person_observer_has_identity_context_without_target_value(self):
        expected = {'people': {'June': 'freckled teen with red glasses'},
                    'state': {'June · location': 'TARGET_VALUE_MUST_NOT_LEAK'}}
        brief = director.fact_observation_brief('June · location', json.dumps(expected), phase='end')
        self.assertIn('freckled teen with red glasses', brief)
        self.assertIn('Frame phase: end', brief)
        self.assertIn('not lettering', brief)
        self.assertIn('posture', brief)
        self.assertNotIn('TARGET_VALUE_MUST_NOT_LEAK', brief)
        self.assertNotIn('base resting', brief)

    def test_person_position_keys_cover_possessives_without_misidentifying_objects(self):
        expected = {'people': {'Mira': 'yellow jacket', 'Noah': 'blue jacket and glasses'},
                    'objects': {'jacket': 'yellow jacket'},
                    'state': {"Mira's position": 'TARGET_MUST_NOT_LEAK'}}
        for key in ("Mira's position", 'Mira’s location', 'position of Noah', 'Mira · position'):
            with self.subTest(key=key):
                brief = director.fact_observation_brief(key, expected)
                self.assertIn('Identify the person from their appearance', brief)
                self.assertIn('whether they face another person', brief)
                self.assertIn('If the relevant subject is hidden or the fact cannot be established', brief)
                self.assertNotIn('TARGET_MUST_NOT_LEAK', brief)
        for key in ("Mira's jacket position", 'Jacket · position', 'position of the jacket'):
            with self.subTest(key=key):
                brief = director.fact_observation_brief(key, expected)
                self.assertIn("Describe the object's position", brief)
                self.assertNotIn('Identify the person from their appearance', brief)

    def test_unobserved_person_position_remains_uncertain(self):
        expected = json.dumps({'state': {"Mira's position": 'at the bus stop'}, 'count': 1,
                               'people': {'Mira': 'yellow jacket'}})
        report = {'count': 1, 'style': {'verdict': 'pass', 'observed': 'Flat cel-painted drawing'},
                  'cast': {'verdict': 'pass', 'observed': 'One person in a yellow jacket'},
                  'state': [{'key': "Mira's position", 'verdict': 'observed', 'observed': 'Mira is obscured'}]}
        audit = json.dumps({'state': [{'key': "Mira's position", 'verdict': 'uncertain',
                                      'reason': 'Her position is not visible'}]})
        result = director.parse_visual_review(json.dumps(report), expected, state_audit=audit)
        self.assertEqual(result['outcome'], 'uncertain')
        self.assertFalse(any(issue['category'] == 'content_issue' for issue in result['issues']))

    def test_shared_design_excludes_cast_and_preserves_props_and_set(self):
        design = 'Avery: purple jacket, short black hair. Brass cup: ridged handle. Robin wears a blue coat. School walls are peach.'
        result = director.scope_shared_design(design, {'Avery': 'purple jacket', 'Robin': 'blue coat'})
        self.assertEqual(result, 'Brass cup: ridged handle. School walls are peach.')
        self.assertEqual(director.scope_shared_design('Avery Street has teal doors.', ['Avery']), 'Avery Street has teal doors.')

    def test_visible_actor_absent_location_is_not_promoted_or_invented(self):
        plan = {'design': 'Peach walls', 'initial': {'Avery · location': 'none'}, 'issues': [],
                'shots': [{'index': 1, 'changes': {}, 'start_checks': ['Avery · location'],
                           'end_checks': [], 'start_cast': ['Avery'], 'end_cast': ['Avery']}]}
        parsed = director.parse_continuity(json.dumps(plan), 1)
        self.assertEqual(parsed['initial'], plan['initial'])
        self.assertIn('starting position is unspecified', parsed['issues'][0])
        self.assertEqual(director.parse_continuity(json.dumps(parsed), 1), parsed)

    def test_cast_rosters_are_trimmed_before_uniqueness_checks(self):
        plan = {'design': '', 'initial': {}, 'issues': [], 'shots': [
            {'index': 1, 'changes': {}, 'start_checks': [], 'end_checks': [],
             'start_cast': [' Mira ', ' Noah'], 'end_cast': ['Mira', 'Noah ']}]}
        parsed = director.parse_continuity(json.dumps(plan), 1)
        self.assertEqual(parsed['shots'][0]['start_cast'], ['Mira', 'Noah'])
        self.assertEqual(parsed['shots'][0]['end_cast'], ['Mira', 'Noah'])
        plan['shots'][0]['start_cast'] = ['Mira', ' mira ']
        with self.assertRaisesRegex(ValueError, 'unique names'):
            director.parse_continuity(json.dumps(plan), 1)

    def test_video_aggregation_retains_outcome_and_sample(self):
        reports = [self.parse() for _ in range(4)]
        reports[2] = self.parse(audit='{}')
        result = director.combine_visual_reviews(reports)
        self.assertEqual(result['outcome'], 'reviewer_error')
        self.assertEqual(result['issues'][0]['sample'], 3)
        self.assertIn('Sample 3:', result['issues'][0]['message'])

    def test_malformed_video_sample_is_not_a_visual_defect(self):
        result = director.combine_visual_reviews([self.parse(), [], self.parse(), self.parse()])
        self.assertEqual(result['outcome'], 'reviewer_error')
        self.assertEqual(result['issues'][0]['code'], 'invalid_video_sample')


class CheckedReviewCacheTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=studio.ROOT)
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        (self.folder / 'frame.png').write_bytes(b'fixed image bytes')
        self.project = {'id': 'reviewfixture', 'look': 'Cel animation'}
        self.worker = object.__new__(studio.Studio)
        self.worker.path = lambda _: self.folder
        self.worker.lock = threading.RLock()
        self.worker.load = lambda _: copy.deepcopy(self.project)
        def save(project):
            self.project.clear()
            self.project.update(copy.deepcopy(project))
            return project
        self.worker.save = Mock(side_effect=save)
        self.worker.comfy = SimpleNamespace(run=Mock(), _timing=SimpleNamespace(metrics={}))
        self.worker._upload = Mock(return_value='uploaded.png')
        self.contracts = {'phase': 'start', 'requirements': {'count': 1, 'state': {}}}
        self.graph_for = Mock(side_effect=lambda uploaded: {
            'judge': {'class_type': 'TextGenerate', 'inputs': {'max_length': 1200, 'image': uploaded}}})

    def result(self, outcome='passed'):
        issues = [] if outcome == 'passed' else [{
            'category': outcome, 'code': 'test_' + outcome,
            'message': 'A specific review result', 'severity': 'warning'}]
        return director.review_result(issues)

    def check(self, contracts=None):
        return self.worker._checked_review(self.project, 'frame.png',
            self.contracts if contracts is None else contracts, self.graph_for, lambda _: None)

    def test_malformed_metadata_cannot_pass_or_be_cached(self):
        incomplete = [
            {'status': 'passed'},
            {**self.result(), 'version': director.REVIEW_VERSION - 1},
            {**self.result(), 'outcome': 'reviewer_error'},
            {**self.result(), 'issues': [{'category': 'unknown', 'code': 'x', 'message': 'x'}]},
            {**self.result(), 'issues': None},
        ]
        for report in incomplete:
            with self.subTest(report=report):
                self.worker._text_graph = Mock(return_value=report)
                result = self.check()
                self.assertEqual((result['status'], result['outcome']), ('needs_review', 'reviewer_error'))
                self.assertEqual(self.worker._text_graph.call_count, 2)
                self.assertEqual(self.project.get('review_cache', {}), {})
        self.worker.comfy.run.assert_not_called()

    def test_reviewer_error_retries_once_without_repainting(self):
        self.worker._text_graph = Mock(return_value=self.result('reviewer_error'))
        result = self.check()
        self.assertEqual(result['outcome'], 'reviewer_error')
        self.assertEqual(self.worker._text_graph.call_count, 2)
        graphs = [call.args[0] for call in self.worker._text_graph.call_args_list]
        self.assertEqual([graph['judge']['inputs']['max_length'] for graph in graphs], [1200, 2400])
        self.assertEqual(graphs[1]['judge']['inputs']['sampling_mode'], 'on')
        self.assertIsInstance(graphs[1]['judge']['inputs']['sampling_mode.seed'], int)
        self.assertEqual(self.worker.comfy._timing.metrics['reviewer_retries'], 1)
        self.worker.comfy.run.assert_not_called()
        self.worker._upload.assert_called_once()

    def test_legacy_comfy_json_error_retries_and_preserves_asset(self):
        self.worker._text_graph = Mock(side_effect=[
            studio.ComfyError("ComfyUI execution failed: Expecting ':' delimiter: line 1 column 689 (char 688)"),
            self.result()])
        self.assertEqual(self.check()['outcome'], 'passed')
        self.assertEqual(self.worker._text_graph.call_count, 2)
        self.assertEqual((self.folder / 'frame.png').read_bytes(), b'fixed image bytes')

    def test_unrelated_comfy_failure_is_not_hidden_as_review_error(self):
        self.worker._text_graph = Mock(side_effect=studio.ComfyError('ComfyUI execution failed: CUDA out of memory'))
        with self.assertRaisesRegex(studio.ComfyError, 'CUDA out of memory'):
            self.check()
        self.assertEqual(self.worker._text_graph.call_count, 1)

    def test_definitive_evidence_is_reused_without_a_second_upload(self):
        for outcome in ('passed', 'content_issue'):
            with self.subTest(outcome=outcome):
                self.project.pop('review_cache', None)
                self.worker._text_graph = Mock(return_value=self.result(outcome))
                self.worker._upload.reset_mock()
                first = self.check()
                first['findings'].append('Caller mutation must not change cached evidence')
                second = self.check()
                self.assertEqual(second['outcome'], outcome)
                self.assertNotIn('Caller mutation must not change cached evidence', second['findings'])
                self.worker._text_graph.assert_called_once()
                self.worker._upload.assert_called_once()
                self.assertEqual(len(self.project['review_cache']), 1)

    def test_contract_content_and_review_version_invalidate_the_cache(self):
        self.worker._text_graph = Mock(side_effect=lambda *args: self.result())
        self.check()
        self.check()
        changed = copy.deepcopy(self.contracts)
        changed['requirements']['count'] = 2
        self.check(changed)
        (self.folder / 'frame.png').write_bytes(b'new image bytes')
        self.check(changed)
        with patch.object(director, 'REVIEW_VERSION', director.REVIEW_VERSION + 1):
            self.check(changed)
        with patch.object(director, 'REVIEW_PROMPT_VERSION', director.REVIEW_PROMPT_VERSION + 1):
            self.check(changed)
        self.assertEqual(self.worker._text_graph.call_count, 5)
        self.assertEqual(len(self.project['review_cache']), 5)

    def test_uncertain_and_broken_checks_are_not_persistent_cache_hits(self):
        for outcome, calls in [('uncertain', 2), ('reviewer_error', 4)]:
            with self.subTest(outcome=outcome):
                self.worker._text_graph = Mock(return_value=self.result(outcome))
                self.check()
                self.check()
                self.assertEqual(self.worker._text_graph.call_count, calls)
                self.assertEqual(self.project.get('review_cache', {}), {})
        self.worker.comfy.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
