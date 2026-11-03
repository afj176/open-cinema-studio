"""Regressions for a playable draft without laundering visual findings."""
from pathlib import Path
import sys
import tempfile
import threading
import itertools
import queue
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from test_asset_dependencies import fixture
import studio


def review(outcome='content_issue', snapshot=None, count=1):
    return {'version': studio.director.REVIEW_VERSION,
            'status': 'passed' if outcome == 'passed' else 'needs_review',
            'outcome': outcome, 'of': snapshot,
            'findings': [] if outcome == 'passed' else ['Extra foreground actor'],
            'issues': [{'category': 'content_issue', 'message': f'Visible defect {index}'}
                       for index in range(count)] if outcome == 'content_issue' else []}


class DraftPipelineTests(unittest.TestCase):
    def _temporal_review(self, field='style'):
        samples = []
        for index in range(4):
            evidence = {field:{'verdict':'pass' if index < 2 else 'fail', 'observed':'Visible character rendering'}}
            issues = [] if index < 2 else [{'category':'content_issue','code':field+'_mismatch',
                                             'message':'Observed visual mismatch','severity':'warning'}]
            samples.append(studio.director.review_result(issues, evidence=evidence))
        return studio.director.combine_visual_reviews(samples)

    def test_temporal_drift_suggests_optional_new_take_only_for_repeated_valid_evidence(self):
        for field in ('style','cast'):
            with self.subTest(field=field):
                result = self._temporal_review(field)
                suggestion = studio.temporal_drift_suggestion(result)
                self.assertEqual(suggestion['kind'], field)
                self.assertEqual(suggestion['samples'], [3,4])
                self.assertIn('keeping the original', suggestion['message'])

    def test_temporal_drift_never_suggests_on_uncertain_broken_or_single_sample(self):
        for category in ('uncertain','reviewer_error'):
            review = self._temporal_review()
            review['samples'][1] = studio.director.review_result([{'category':category,'code':'bad_evidence',
                'message':'Not reliable','severity':'warning'}], evidence={'style':{'verdict':'uncertain','observed':'Unknown'}})
            review = studio.director.combine_visual_reviews(review['samples'])
            self.assertIsNone(studio.temporal_drift_suggestion(review))
        review = self._temporal_review()
        review['samples'][3] = studio.director.review_result([], evidence={'style':{'verdict':'pass','observed':'Stable'}})
        self.assertIsNone(studio.temporal_drift_suggestion(studio.director.combine_visual_reviews(review['samples'])))
        review = self._temporal_review()
        review['samples'][0]['evidence']['style']['verdict'] = 'fail'
        self.assertIsNone(studio.temporal_drift_suggestion(review))

    def test_video_review_records_suggestion_without_enqueuing_or_replacing_current_take(self):
        worker, project, shot = self.harness()
        candidate = studio.current_take(shot, 'video')
        candidate['of'] = studio.video_inputs(project, shot)
        result = self._temporal_review()
        result['of'] = candidate['of']
        worker._require_plan = Mock(return_value=project)
        worker._review_video = Mock(return_value=result)
        worker.enqueue = Mock()
        worker._run_review({'project':project['id'], 'shot':shot['id'], 'candidate_name':candidate['name']}, lambda _: None)
        self.assertEqual(shot['video'], candidate['name'])
        self.assertEqual(shot['quality']['video']['repair_suggestion']['kind'], 'style')
        worker.enqueue.assert_not_called()

    def test_manual_approval_is_not_replaced_by_a_later_review_or_given_a_retry(self):
        worker, project, shot = self.harness()
        candidate = studio.current_take(shot, 'video')
        candidate['of'] = studio.video_inputs(project, shot)
        approved = review('passed', candidate['of'])
        approved['director_review'] = {'reason':'Chosen by director'}
        candidate['review'] = approved
        result = self._temporal_review()
        result['of'] = candidate['of']
        worker._require_plan = Mock(return_value=project)
        worker._review_video = Mock(return_value=result)
        worker.enqueue = Mock()
        worker._run_review({'project':project['id'], 'shot':shot['id'], 'candidate_name':candidate['name']}, lambda _: None)
        self.assertIs(candidate['review'], approved)
        self.assertNotIn('repair_suggestion', candidate['latest_automated_review'])
        worker.enqueue.assert_not_called()

    def test_draft_keyframe_defers_check_without_falsely_approving_it(self):
        for mode in ('normal', 'fast'):
            with self.subTest(mode=mode):
                worker, project, shot = self.harness()
                project['ai_mode'] = mode
                shot['keyframe'] = None
                worker.enqueue = Mock()
                worker._repair_frame = Mock()
                worker._finish_keyframe(project, shot, 'new.png', 'prompt', 7, {'kind':'shot'}, lambda _: None, {}, 0)
                take = studio.current_take(shot, 'keyframe')
                self.assertEqual(take['name'], 'new.png')
                self.assertTrue(studio.review_pending(take))
                self.assertFalse(studio.review_passed(take))
                self.assertTrue(studio.take_usable(project, take))
                self.assertEqual(take['review']['of'], studio.visual_inputs(project, shot))
                worker._review_image.assert_not_called()
                worker._repair_frame.assert_not_called()
                self.assertEqual(worker.enqueue.call_args.args[0], 'review_frame')
                self.assertEqual(worker.enqueue.call_args.kwargs['candidate_name'], 'new.png')
                self.assertGreater(studio.PRIORITY['review_frame'], studio.PRIORITY.get('stitch', 2))

    def test_deferred_frame_review_checks_original_without_repainting(self):
        worker, project, shot = self.harness()
        expected = studio.visual_inputs(project, shot)
        take = studio.current_take(shot, 'keyframe')
        take['review'] = review('uncertain', expected)
        worker._require_plan = Mock(return_value=project)
        worker._review_image = Mock(return_value=review('content_issue', expected))
        worker._repair_frame = Mock()
        worker._run_review_frame({'project':project['id'], 'shot':shot['id'], 'candidate_name':take['name']}, lambda _: None)
        worker._repair_frame.assert_not_called()
        self.assertEqual(take['review']['outcome'], 'content_issue')
        self.assertEqual(shot['quality']['keyframe']['name'], take['name'])
        self.assertEqual(shot['keyframe'], take['name'])

    def test_deferred_frame_review_never_checks_outdated_image(self):
        worker, project, shot = self.harness()
        take = studio.current_take(shot, 'keyframe')
        take['review'] = review('uncertain', studio.visual_inputs(project, shot))
        shot['action'] = 'Changed since rendering'
        worker._require_plan = Mock(return_value=project)
        with self.assertRaisesRegex(RuntimeError, 'out of date'):
            worker._run_review_frame({'project':project['id'], 'shot':shot['id'], 'candidate_name':take['name']}, lambda _: None)
        worker._review_image.assert_not_called()

    def test_failed_deferred_frame_check_does_not_block_draft_work(self):
        worker, project, shot = self.harness()
        later = {'project':project['id'], 'shot':shot['id'], 'kind':'video', 'state':'queued'}
        cut = {'project':project['id'], 'shot':None, 'kind':'stitch', 'state':'queued'}
        worker.jobs = [later, cut]
        worker._block_dependents({'project':project['id'], 'shot':shot['id'], 'kind':'review_frame', 'review_policy':'draft'})
        self.assertEqual((later['state'], cut['state']), ('queued', 'queued'))

    def test_strict_frame_review_runs_before_video(self):
        worker, project, shot = self.harness('strict')
        worker.jobs = []
        worker.queue = queue.PriorityQueue()
        worker.order = itertools.count()
        worker._save_jobs = Mock()
        checking = worker.enqueue('review_frame', project['id'], shot['id'], candidate_name='frame.png')
        worker.enqueue('video', project['id'], shot['id'])
        self.assertEqual(worker.queue.get()[2]['id'], checking['id'])

    def test_switching_to_strict_does_not_reuse_a_queued_draft_check(self):
        worker, project, shot = self.harness()
        worker.jobs = []
        worker.queue = queue.PriorityQueue()
        worker.order = itertools.count()
        worker._save_jobs = Mock()
        draft = worker.enqueue('review_frame', project['id'], shot['id'], candidate_name='frame.png', review_policy='draft')
        strict = worker.enqueue('review_frame', project['id'], shot['id'], candidate_name='frame.png', review_policy='strict')
        self.assertNotEqual(draft['id'], strict['id'])
        self.assertEqual(worker.queue.get()[2]['id'], strict['id'])
        self.assertEqual(draft['review_policy'], 'draft')

    def test_strict_reviews_precede_stitch_and_retries_keep_their_candidate(self):
        worker, project, shot = self.harness('strict')
        worker.jobs = []
        worker.queue = queue.PriorityQueue()
        worker.order = itertools.count()
        worker._save_jobs = Mock()
        checking = worker.enqueue('review', project['id'], shot['id'], candidate_name='new.mp4')
        worker.enqueue('stitch', project['id'])
        self.assertEqual(worker.queue.get()[2]['id'], checking['id'])
        checking['state'] = 'interrupted'
        retried = worker.retry_job(checking['id'])
        self.assertEqual(retried['candidate_name'], 'new.mp4')
        self.assertEqual(retried['review_policy'], 'strict')
        other = worker.enqueue('review', project['id'], shot['id'], candidate_name='other.mp4')
        self.assertNotEqual(retried['id'], other['id'])

    def test_script_changes_block_mastering_before_gpu_work(self):
        worker, project, shot = self.harness('strict')
        project['film'] = 'existing.mp4'
        project['film_of'] = studio.film_inputs(project)
        shot['action'] = 'A changed performance'
        with self.assertRaisesRegex(RuntimeError, 'cut changed'):
            worker._run_master({'project':project['id']}, lambda _: None)
        worker.comfy.run.assert_not_called()

    def test_deferred_review_targets_new_candidate_not_approved_current_clip(self):
        worker, project, shot = self.harness()
        expected = studio.video_inputs(project, shot)
        current = studio.current_take(shot, 'video')
        current['review'] = review('passed', expected)
        shot['takes']['video'].append({'name':'new-candidate.mp4', 'of':expected, 'keyframe':shot['keyframe'], 'review':review('uncertain', expected)})
        worker._require_plan = Mock(return_value=project)
        worker._review_video = Mock(return_value=review('uncertain', expected))
        worker._run_review({'project':project['id'],'shot':shot['id'],'candidate_name':'new-candidate.mp4'}, lambda _: None)
        self.assertEqual(worker._review_video.call_args.args[2], 'new-candidate.mp4')
        self.assertEqual(shot['video'], 'clip.mp4')
        self.assertTrue(studio.review_passed(current))

    def test_api_skips_empty_fact_passes_but_editable_canvas_keeps_them(self):
        import json
        expected = json.dumps({'state': {}, 'count': 1, 'people': {'Avery': 'yellow coat'}})
        optimized = studio.graphs.visual_review_graph('frame.png', expected, 'cartoon')
        editable = studio.graphs.visual_review_graph('frame.png', expected, 'cartoon', optimize=False)
        self.assertNotIn('fact_observations', optimized)
        self.assertNotIn('compare', optimized)
        self.assertIn('fact_observations', editable)
        self.assertIn('compare', editable)

    def test_unknown_visible_actor_location_is_flagged_not_drawn_as_absence(self):
        _, project, shot = self.harness()
        project['cast'] = 'Avery, yellow coat'
        project['scene_state'] = {'Avery · location':'none', 'Door · position':'none'}
        shot.update(start_cast=['Avery'], start_checks=['Avery · location', 'Door · position'])
        requirements = studio.review_requirements(project, shot, 'start')
        self.assertEqual(requirements['state'], {'Door · position':'none'})
        self.assertEqual(requirements['unresolved_facts'], ['Avery · location'])

    def test_offscreen_mentions_do_not_add_actors_to_motion(self):
        worker, project, shot = self.harness()
        project['cast'] = 'Avery, yellow coat'
        project['characters'] = 'Morgan: purple coat\nRowan: teal jacket'
        shot.update(start_cast=['Avery'], end_cast=['Avery', 'Morgan'],
                    action='Avery glances toward Rowan outside the frame; Morgan enters.')
        lead, others = studio.performing_cast(project, shot)
        self.assertTrue(lead)
        self.assertIn('Morgan', others)
        self.assertNotIn('Rowan', others)

    def test_draft_video_defers_review_until_after_playable_cut(self):
        worker, project, shot = self.harness()
        worker._require_plan = Mock(return_value=project)
        worker._review_video = Mock()
        worker._record_candidate = Mock()
        worker.enqueue = Mock()
        take = studio.current_take(shot, 'keyframe')
        take['review'] = review('passed', studio.visual_inputs(project, shot))
        job = {'project': project['id'], 'shot': shot['id'], 'ai_mode':'normal', 'review_policy':'draft'}
        with patch.object(studio, 'frame_stale', return_value=False), patch.object(studio, 'duration', return_value=1):
            worker._run_video(job, lambda _: None)
        worker._review_video.assert_not_called()
        recorded = worker._record_candidate.call_args.args[4]
        self.assertEqual(recorded['outcome'], 'uncertain')
        self.assertEqual(recorded['issues'][0]['code'], 'pending_review')
        self.assertEqual(worker.enqueue.call_args.args[0], 'review')
        self.assertGreater(studio.PRIORITY['review'], studio.PRIORITY.get('stitch', 2))

    def test_empty_film_is_pending_and_a_watermark_needs_explicit_clean_cut(self):
        worker, project, shot = self.harness()
        self.assertEqual(studio.film_review(project)['status'], 'pending')
        project['film'] = 'draft.mp4'
        project['film_of'] = studio.film_inputs(project)
        project['film_marked_draft'] = True
        for kind in ('keyframe', 'video'):
            studio.current_take(shot, kind)['review'] = review('passed')
        summary = studio.film_review(project)
        self.assertEqual(summary['status'], 'draft')
        self.assertTrue(summary['ready_to_finalize'])

    def harness(self, policy='draft'):
        project, shot = fixture()
        project['review_policy'] = policy
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.load = lambda _: project
        worker.save = Mock(side_effect=lambda fresh: fresh)
        worker.comfy = SimpleNamespace(run=Mock(return_value=[{'filename': 'repair.png'}]), download=Mock())
        worker._upload = Mock(return_value='input.png')
        worker._review_image = Mock(return_value=review('passed'))
        worker._assemble = Mock()
        worker._waveform = Mock(return_value=None)
        worker._title_clip = Mock(return_value=None)
        worker.path = lambda _: Path('unused-scratch')
        return worker, project, shot

    def test_draft_promotes_flagged_candidate_without_changing_review_status(self):
        worker, project, shot = self.harness()
        shot['keyframe'] = None
        candidate = review(snapshot=studio.visual_inputs(project, shot))
        worker._record_candidate(project['id'], shot['id'], 'keyframe', 'draft.png', candidate)
        self.assertEqual(shot['keyframe'], 'draft.png')
        self.assertFalse(studio.review_passed(studio.current_take(shot, 'keyframe')))
        self.assertTrue(studio.take_usable(project, studio.current_take(shot, 'keyframe')))
        self.assertEqual(shot['quality']['keyframe']['status'], 'needs_review')

    def test_strict_keeps_flagged_candidate_unselected(self):
        worker, project, shot = self.harness('strict')
        original = shot['keyframe']
        with self.assertRaisesRegex(RuntimeError, 'needs review'):
            worker._record_candidate(project['id'], shot['id'], 'keyframe', 'flagged.png', review())
        self.assertEqual(shot['keyframe'], original)
        self.assertIn('flagged.png', [take['name'] for take in shot['takes']['keyframe']])

    def test_flagged_draft_never_replaces_current_approved_take(self):
        worker, project, shot = self.harness()
        snapshot = studio.visual_inputs(project, shot)
        current = studio.current_take(shot, 'keyframe')
        current['review'] = review('passed', snapshot)
        worker._record_candidate(project['id'], shot['id'], 'keyframe', 'worse.png', review(snapshot=snapshot))
        self.assertEqual(shot['keyframe'], 'frame.png')
        self.assertEqual(shot['quality']['keyframe']['name'], 'worse.png')
        self.assertIn('worse.png', [take['name'] for take in shot['takes']['keyframe']])

    def test_unknown_or_broken_review_never_repaints_pixels(self):
        for policy in ('draft', 'strict'):
            for outcome in ('uncertain', 'reviewer_error'):
                with self.subTest(policy=policy, outcome=outcome):
                    worker, project, shot = self.harness(policy)
                    candidate = review(outcome)
                    name, result = worker._repair_frame(project, shot, 'original.png', candidate, lambda _: None, 'start')
                    self.assertEqual((name, result), ('original.png', candidate))
                    worker.comfy.run.assert_not_called()

    def test_content_issue_gets_one_targeted_draft_repair(self):
        worker, project, shot = self.harness()
        improved = review('passed')
        worker._review_image.return_value = improved
        name, result = worker._repair_frame(project, shot, 'original.png', review(), lambda _: None, 'start')
        self.assertEqual(worker.comfy.run.call_count, 1)
        self.assertTrue(name.startswith('repair_start_'))
        self.assertIs(result, improved)

    def test_regressing_repair_retains_original_best_candidate(self):
        worker, project, shot = self.harness()
        original = review(count=1)
        worker._review_image.return_value = review(count=2)
        name, result = worker._repair_frame(project, shot, 'best.png', original, lambda _: None, 'start')
        self.assertEqual(name, 'best.png')
        self.assertIs(result, original)
        self.assertTrue(any(item.get('not_selected') for item in shot['frame_repairs']))

    def test_uncertain_repair_is_not_mistaken_for_improvement(self):
        worker, project, shot = self.harness()
        original = review()
        worker._review_image.return_value = review('reviewer_error')
        name, result = worker._repair_frame(project, shot, 'best.png', original, lambda _: None, 'start')
        self.assertEqual(name, 'best.png')
        self.assertIs(result, original)

    def test_strict_repair_budget_remains_bounded(self):
        worker, project, shot = self.harness('strict')
        worker._review_image.side_effect = [review(count=1), review('passed')]
        worker._repair_frame(project, shot, 'original.png', review(count=2), lambda _: None, 'start')
        self.assertEqual(worker.comfy.run.call_count, 2)

    def test_draft_cut_can_include_flagged_clip_without_approving_it(self):
        worker, project, shot = self.harness()
        video = studio.current_take(shot, 'video')
        video['review'] = review(snapshot=studio.video_inputs(project, shot))
        studio.current_take(shot, 'keyframe')['review'] = review('passed', studio.visual_inputs(project, shot))
        with tempfile.TemporaryDirectory(dir=studio.ROOT) as folder, patch.object(studio, 'duration', return_value=4):
            worker.path = lambda _: Path(folder)
            (Path(folder) / shot['video']).write_bytes(b'clip fixture')
            worker._run_stitch({'project': project['id']}, lambda _: None)
        worker._assemble.assert_called_once()
        self.assertTrue(project.get('film'))
        self.assertFalse(studio.review_passed(video))
        self.assertEqual(studio.film_review(project)['status'], 'draft')
        self.assertEqual(studio.film_review(project)['findings'][0]['kind'], 'video')

    def test_draft_still_rejects_unplayable_media(self):
        worker, project, shot = self.harness()
        studio.current_take(shot, 'video')['review'] = review(snapshot=studio.video_inputs(project, shot))
        with tempfile.TemporaryDirectory(dir=studio.ROOT) as folder, patch.object(studio, 'duration', return_value=0):
            worker.path = lambda _: Path(folder)
            (Path(folder) / shot['video']).write_bytes(b'broken fixture')
            with self.assertRaises(RuntimeError):
                worker._run_stitch({'project': project['id']}, lambda _: None)
        worker._assemble.assert_not_called()

    def test_strict_cut_blocks_flagged_clip(self):
        worker, project, shot = self.harness('strict')
        studio.current_take(shot, 'video')['review'] = review(snapshot=studio.video_inputs(project, shot))
        with self.assertRaises(RuntimeError):
            worker._run_stitch({'project': project['id']}, lambda _: None)
        worker._assemble.assert_not_called()

    def test_unseen_unrelated_fact_does_not_invalidate_frame_or_video(self):
        _, project, shot = self.harness()
        project['scene_state'] = {'Cup · held by': 'Lead', 'Offscreen door · lock': 'locked'}
        shot['start_checks'] = ['Cup · held by']
        shot['end_checks'] = ['Cup · held by']
        shot['state_changes'] = {'Cup · held by': 'Tavi'}
        before_frame = studio.visual_inputs(project, shot)
        before_video = studio.video_inputs(project, shot)
        project['scene_state']['Offscreen door · lock'] = 'unlocked'
        self.assertEqual(studio.visual_inputs(project, shot), before_frame)
        self.assertEqual(studio.video_inputs(project, shot), before_video)
        project['scene_state']['Cup · held by'] = 'Tavi'
        self.assertNotEqual(studio.visual_inputs(project, shot), before_frame)
        self.assertNotEqual(studio.video_inputs(project, shot), before_video)

    def test_queued_policy_context_takes_precedence_and_restores(self):
        project = {'review_policy': 'strict'}
        with studio.using_review_policy('draft'):
            self.assertTrue(studio.draft_mode(project))
        self.assertFalse(studio.draft_mode(project))
