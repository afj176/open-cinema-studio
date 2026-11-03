"""A linked-frame retry must keep evidence and never promote an uncertain result."""
import copy
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from test_asset_dependencies import fixture
import studio


def cast_review(expected=2, observed=3):
    issue = {'category': 'content_issue', 'code': 'cast_count_mismatch',
             'severity': 'blocking', 'message': 'Extra visible character'}
    return studio.director.review_result([issue], expected_count=expected, observed_count=observed)


def image_review(project, shot, outcome='extra', count=3):
    if outcome == 'extra':
        issues = [{'category':'content_issue','code':'cast_count_mismatch',
                   'severity':'blocking','message':'Visible cast count differs'}]
    elif outcome == 'uncertain':
        issues = [{'category':'uncertain','code':'cast_count_unverifiable',
                   'severity':'warning','message':'Could not count'}]
    else:
        issues = []
    result = studio.director.review_result(issues, evidence={'count':count})
    result['of'] = studio.visual_inputs(project, shot)
    return result


class ReframeRecoveryTests(unittest.TestCase):
    def harness(self, mode='draft'):
        project, shot = fixture()
        project['review_policy'] = mode
        shot.update(frame_source='previous_end', keyframe=None, video=None,
                    takes={'keyframe': [], 'video': []})
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.load = lambda _: project
        worker.save = lambda value: value
        worker.comfy = Mock()
        worker._metric = Mock()
        worker._render_checked = Mock(return_value=([{'filename':'alternate.png'}], 1000004, {}))
        worker.path = lambda _: Path(self.temp.name)
        return worker, project, shot

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime')
        self.addCleanup(self.temp.cleanup)

    def recover(self, worker, project, shot, quick, job=None):
        return worker._recover_linked_cast(project, shot, 'original.png', 'directed prompt', 1,
            {'kind':'shot','frame_source':'previous_end','visual':studio.visual_inputs(project, shot)},
            quick, 2, 'previous.png', 'scratch/frame', 'qwen', lambda _: None, job if job is not None else {}, 1)

    def test_single_alternate_is_retained_but_never_auto_promoted_on_cast_pass(self):
        for mode in ('draft', 'strict'):
            with self.subTest(mode=mode):
                worker, project, shot = self.harness(mode)
                worker._review_image = Mock(side_effect=[image_review(project, shot), image_review(project, shot, 'passed', 2)])
                name, prompt, seed, review, attempted = self.recover(worker, project, shot, cast_review())
                self.assertTrue(attempted)
                self.assertEqual(name, 'original.png')
                self.assertEqual(studio.review_outcome(review), 'content_issue')
                self.assertEqual(seed, 1)
                self.assertEqual(worker._render_checked.call_count, 1)
                self.assertIsNone(shot['keyframe'])  # selection is a separate, guarded finish step
                self.assertEqual(len(shot['takes']['keyframe']), 2)
                self.assertEqual(shot['takes']['keyframe'][0]['name'], 'original.png')
                self.assertEqual(shot['takes']['keyframe'][1]['repaired_from'], 'original.png')
                self.assertEqual(studio.review_outcome(shot['takes']['keyframe'][1]['review']), 'uncertain')
                self.assertEqual(shot['takes']['keyframe'][1]['review']['issues'][0]['code'], 'viewpoint_unverified')

    def test_retry_keeps_returning_character_identity_reference(self):
        worker, project, shot = self.harness()
        worker._review_image = Mock(side_effect=[image_review(project, shot), image_review(project, shot, 'passed', 2)])
        worker._recover_linked_cast(project, shot, 'original.png', 'directed prompt', 1,
            {'kind':'shot','frame_source':'previous_end','visual':studio.visual_inputs(project, shot)},
            cast_review(), 2, 'previous.png', 'scratch/frame', 'qwen', lambda _: None, {}, 1,
            second_reference='returning.png')
        graph = worker._render_checked.call_args.args[0]
        self.assertEqual(graph['16']['inputs']['image'], 'returning.png')

    def test_retry_keeps_both_memory_shot_references(self):
        worker, project, shot = self.harness()
        worker._review_image = Mock(side_effect=[image_review(project, shot), image_review(project, shot, 'passed', 2)])
        worker._recover_linked_cast(project, shot, 'original.png', 'directed prompt', 1,
            {'kind':'shot','frame_source':'storyboard','visual':studio.visual_inputs(project, shot)},
            cast_review(), 2, 'board.png', 'scratch/frame', 'qwen', lambda _: None, {}, 1,
            second_reference='portrait.png', third_reference='memory.png')
        graph = worker._render_checked.call_args.args[0]
        self.assertEqual(graph['16']['inputs']['image'], 'portrait.png')
        self.assertEqual(graph['18']['inputs']['image'], 'memory.png')

    def test_uncertain_or_worse_alternate_keeps_original_and_both_takes(self):
        for result in ('uncertain', 'extra'):
            with self.subTest(result=result):
                worker, project, shot = self.harness()
                worker._review_image = Mock(side_effect=[image_review(project, shot), image_review(project, shot, result)])
                name, _, _, review, attempted = self.recover(worker, project, shot, cast_review())
                self.assertTrue(attempted)
                self.assertEqual(name, 'original.png')
                self.assertEqual(studio.review_outcome(review), 'content_issue')
                self.assertEqual(len(shot['takes']['keyframe']), 2)
                self.assertIsNone(shot['keyframe'])

    def test_correct_count_cannot_promote_an_unconfirmed_or_reversed_viewpoint(self):
        worker, project, shot = self.harness()
        worker._review_image = Mock(side_effect=[image_review(project, shot), image_review(project, shot, 'passed', 2)])
        name, _, _, review, attempted = self.recover(worker, project, shot, cast_review())
        self.assertTrue(attempted)
        self.assertEqual(name, 'original.png')
        self.assertEqual(studio.review_outcome(review), 'content_issue')
        alternate = shot['takes']['keyframe'][1]
        self.assertEqual(studio.review_outcome(alternate['review']), 'uncertain')
        self.assertEqual(alternate['review']['issues'][0]['code'], 'viewpoint_unverified')

    def test_director_can_inspect_and_explicitly_accept_the_alternate_in_strict_mode(self):
        worker, project, shot = self.harness('strict')
        worker._review_image = Mock(side_effect=[image_review(project, shot), image_review(project, shot, 'passed', 2)])
        self.recover(worker, project, shot, cast_review())
        alternate = shot['takes']['keyframe'][1]
        with patch.object(studio, 'plan_usable', return_value=True):
            worker.accept_review(project['id'], shot['id'], 'keyframe', alternate['name'], 'I checked the view')
        self.assertEqual(shot['keyframe'], alternate['name'])
        self.assertEqual(alternate['review']['director_review']['reason'], 'I checked the view')
        self.assertEqual(alternate['review']['automated_status'], 'needs_review')

    def test_no_retry_on_inconclusive_or_unconfirmed_count(self):
        for quick, confirmed in (({}, None), (cast_review(observed=1), None),
                                 (cast_review(), 'uncertain'), (cast_review(), 'different')):
            with self.subTest(quick=quick, confirmed=confirmed):
                worker, project, shot = self.harness()
                review = image_review(project, shot, 'uncertain' if confirmed == 'uncertain' else 'extra',
                                      count=4 if confirmed == 'different' else 3)
                worker._review_image = Mock(return_value=review)
                _, _, _, _, attempted = self.recover(worker, project, shot, quick)
                self.assertFalse(attempted)
                worker._render_checked.assert_not_called()

    def test_disagreement_or_invalid_full_review_cannot_be_promoted_as_pass(self):
        for kind in ('passed', 'mixed', 'missing', 'malformed'):
            with self.subTest(kind=kind):
                worker, project, shot = self.harness()
                if kind == 'passed':
                    full = image_review(project, shot, 'passed', count=2)
                elif kind == 'mixed':
                    full = image_review(project, shot, 'extra', count=2)
                elif kind == 'missing':
                    full = image_review(project, shot, 'passed', count=None)
                else:
                    full = {'version':studio.director.REVIEW_VERSION, 'status':'passed', 'outcome':'passed'}
                worker._review_image = Mock(return_value=full)
                name, _, _, review, attempted = self.recover(worker, project, shot, cast_review())
                self.assertEqual(name, 'original.png')
                self.assertFalse(attempted)
                self.assertNotEqual(studio.review_outcome(review), 'passed')
                self.assertEqual(shot['takes']['keyframe'][0]['review'], review)
                self.assertTrue(studio.valid_review_result(review))
                if kind != 'malformed':
                    self.assertTrue(any(issue['code'] == 'cast_count_disagreement' for issue in review['issues']))
                worker._render_checked.assert_not_called()

    def test_interruption_keeps_original_and_never_promotes_it(self):
        worker, project, shot = self.harness()
        worker._review_image = Mock(side_effect=studio.ComfyError('interrupted'))
        with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
            self.recover(worker, project, shot, cast_review())
        self.assertEqual([t['name'] for t in shot['takes']['keyframe']], ['original.png'])
        self.assertIsNone(shot['keyframe'])

    def test_stop_between_confirmation_and_retry_does_not_submit_gpu_work(self):
        worker, project, shot = self.harness()
        job = {}
        def confirm(*_args, **_kwargs):
            job['stopped'] = True
            return image_review(project, shot)
        worker._review_image = Mock(side_effect=confirm)
        with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
            self.recover(worker, project, shot, cast_review(), job)
        worker._render_checked.assert_not_called()
        self.assertEqual([t['name'] for t in shot['takes']['keyframe']], ['original.png'])
        self.assertIsNone(shot['keyframe'])

    def test_stop_after_alternate_download_keeps_both_candidates_without_review(self):
        worker, project, shot = self.harness()
        job = {}
        worker._review_image = Mock(return_value=image_review(project, shot))
        worker.comfy.download.side_effect = lambda *_args: job.update(stopped=True)
        with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
            self.recover(worker, project, shot, cast_review(), job)
        self.assertEqual(worker._review_image.call_count, 1)
        self.assertEqual(len(shot['takes']['keyframe']), 2)
        self.assertIsNone(shot['keyframe'])

    def test_stopped_job_cannot_submit_or_promote_even_when_viewpoint_passed(self):
        worker, project, shot = self.harness()
        with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
            worker._submit_for_job({}, {'stopped':True})
        worker.comfy.submit.assert_not_called()
        review = image_review(project, shot, 'passed', 2)
        with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
            worker._finish_keyframe(project, shot, 'alternate.png', 'prompt', 1,
                                    {'frame_source':'previous_end'}, lambda _: None, {'stopped':True}, 1,
                                    known_review=review, allow_repair=False)
        self.assertIsNone(shot['keyframe'])
        self.assertEqual([t['name'] for t in shot['takes']['keyframe']], ['alternate.png'])

    def test_worker_marks_late_stop_cancelled_even_if_handler_returns_normally(self):
        worker, _, _ = self.harness()
        finished = threading.Event()
        worker.queue = queue.PriorityQueue()
        job = {'kind':'fake', 'state':'queued', 'project':'scratch', 'created':0}
        worker.jobs = [job]
        worker.queue.put((0, 0, job))
        worker.comfy = SimpleNamespace(_timing=threading.local())
        worker._run_fake = lambda current, _tick: current.update(stopped=True)
        worker._save_jobs = lambda: finished.set() if job['state'] == 'cancelled' else None
        thread = threading.Thread(target=worker._worker, daemon=True)
        thread.start()
        self.assertTrue(finished.wait(2))
        self.assertEqual((job['state'], job['error']), ('cancelled', 'Stopped by you'))

    def test_strict_review_stop_cannot_start_a_repair(self):
        worker, project, shot = self.harness('strict')
        job = {}
        def review_then_stop(*_args, **_kwargs):
            job['stopped'] = True
            return image_review(project, shot)
        worker._review_image = Mock(side_effect=review_then_stop)
        worker._repair_frame = Mock()
        with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
            worker._finish_keyframe(project, shot, 'original.png', 'prompt', 1,
                {'frame_source':'previous_end'}, lambda _: None, job, 1)
        worker._repair_frame.assert_not_called()
        self.assertIn('original.png', [t['name'] for t in shot['takes']['keyframe']])
        self.assertIsNone(shot['keyframe'])

    def test_linked_video_stop_after_keyframe_does_not_start_video(self):
        worker, project, shot = self.harness()
        job = {'project':project['id'], 'shot':shot['id']}
        worker._require_plan = Mock(return_value=project)
        worker._run_keyframe = Mock(side_effect=lambda *_args: job.update(stopped=True))
        with patch.object(studio, 'story_stale', return_value=False):
            with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
                worker._run_video(job, lambda _: None)
        worker.comfy.submit.assert_not_called()
        worker.comfy.run.assert_not_called()

    def test_linked_video_stop_after_download_keeps_clip_unselected(self):
        worker, project, shot = self.harness()
        shot['keyframe'] = 'frame.png'
        review = image_review(project, shot, 'passed', 2)
        shot['takes']['keyframe'].append({'name':'frame.png','review':review})
        job = {'project':project['id'], 'shot':shot['id']}
        worker._require_plan = Mock(return_value=project)
        worker._upload = lambda *_args: 'frame.png'
        worker._run_for_job = Mock(return_value=[{'filename':'clip.mp4'}])
        worker.comfy.download.side_effect = lambda *_args: job.update(stopped=True)
        worker._review_video = Mock()
        with patch.object(studio, 'story_stale', return_value=False), \
             patch.object(studio, 'frame_stale', return_value=False), \
             patch.object(studio, 'plan_usable', return_value=True), \
             patch.object(studio, 'duration', return_value=3.0):
            with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
                worker._run_video(job, lambda _: None)
        worker._review_video.assert_not_called()
        self.assertIsNone(shot['video'])
        self.assertEqual(len(shot['takes']['video']), 1)
        self.assertTrue(studio.review_pending(shot['takes']['video'][0]))

    def test_linked_video_stop_between_upload_and_submit_never_queues_video(self):
        worker, project, shot = self.harness()
        shot['keyframe'] = 'frame.png'
        shot['takes']['keyframe'].append({'name':'frame.png','review':image_review(project, shot, 'passed', 2)})
        job = {'project':project['id'], 'shot':shot['id']}
        worker._require_plan = Mock(return_value=project)
        def stop_during_upload(*_args):
            job['stopped'] = True
            return 'frame.png'
        worker._upload = stop_during_upload
        with patch.object(studio, 'story_stale', return_value=False), \
             patch.object(studio, 'frame_stale', return_value=False), \
             patch.object(studio, 'plan_usable', return_value=True):
            with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
                worker._run_video(job, lambda _: None)
        worker.comfy.submit.assert_not_called()
        self.assertIsNone(shot['video'])

    def test_linked_video_keeps_intervening_director_edits_and_unselected_clip(self):
        for edit in ('staging', 'video_selection', 'frame_selection', 'frame_approval'):
            with self.subTest(edit=edit):
                worker, project, shot = self.harness()
                shot['keyframe'] = 'frame.png'
                shot['takes']['keyframe'].append({'name':'frame.png', 'review':image_review(project, shot, 'passed', 2)})
                snapshot = copy.deepcopy(project)
                worker._require_plan = Mock(return_value=snapshot)
                worker._upload = lambda *_args: 'frame.png'
                worker._run_for_job = Mock(return_value=[{'filename':'clip.mp4'}])
                worker.enqueue = Mock()
                def change_on_download(*_args):
                    if edit == 'staging':
                        shot['start_frame'] = 'A different camera direction'
                    elif edit == 'video_selection':
                        shot['video'] = 'director.mp4'
                        shot['takes']['video'].append({'name':'director.mp4', 'keyframe':'frame.png'})
                    elif edit == 'frame_selection':
                        shot['keyframe'] = 'director.png'
                        shot['takes']['keyframe'].append({'name':'director.png', 'review':{}})
                    else:
                        shot['takes']['keyframe'][0]['review']['director_review'] = {'reason':'chosen'}
                worker.comfy.download.side_effect = change_on_download
                with patch.object(studio, 'story_stale', return_value=False), \
                     patch.object(studio, 'frame_stale', return_value=False), \
                     patch.object(studio, 'plan_usable', return_value=True), \
                     patch.object(studio, 'duration', return_value=3.0):
                    with self.assertRaisesRegex(RuntimeError, 'changed while rendering'):
                        worker._run_video({'project':project['id'], 'shot':shot['id']}, lambda _: None)
                self.assertEqual(shot['video'], 'director.mp4' if edit == 'video_selection' else None)
                self.assertEqual(shot['keyframe'], 'director.png' if edit == 'frame_selection' else 'frame.png')
                candidate = next(t for t in shot['takes']['video'] if t['name'] != 'director.mp4')
                self.assertTrue(studio.review_pending(candidate))
                worker.enqueue.assert_not_called()

    def test_linked_video_without_intervening_edits_becomes_current(self):
        worker, project, shot = self.harness()
        shot['keyframe'] = 'frame.png'
        shot['takes']['keyframe'].append({'name':'frame.png', 'review':image_review(project, shot, 'passed', 2)})
        worker._require_plan = Mock(return_value=copy.deepcopy(project))
        worker._upload = lambda *_args: 'frame.png'
        worker._run_for_job = Mock(return_value=[{'filename':'clip.mp4'}])
        worker.enqueue = Mock()
        with patch.object(studio, 'story_stale', return_value=False), \
             patch.object(studio, 'frame_stale', return_value=False), \
             patch.object(studio, 'plan_usable', return_value=True), \
             patch.object(studio, 'duration', return_value=3.0):
            worker._run_video({'project':project['id'], 'shot':shot['id']}, lambda _: None)
        self.assertTrue(shot['video'])
        self.assertTrue(studio.review_pending(studio.current_take(shot, 'video')))
        self.assertEqual(worker.enqueue.call_args.args[0], 'review')

    def test_continue_video_keeps_derived_start_and_can_become_current(self):
        worker, project, shot = self.harness()
        prior = studio.new_shot(action='Earlier action', video='prior.mp4')
        project['shots'].insert(0, prior)
        shot.update(transition='continue', frame_source='storyboard', start_cast=['Lead', 'Tavi'])
        project['character_references'] = {'Tavi': {'image':'tavi.png','source':'upload'}}
        worker._require_plan = Mock(return_value=copy.deepcopy(project))
        worker._last_frame = Mock(return_value='prior_last.png')
        worker._upload = lambda *_args: 'frame.png'
        worker._run_for_job = Mock(return_value=[{'filename':'clip.mp4'}])
        worker._review_image = Mock(side_effect=lambda p, s, _name, _tick, **_kwargs: image_review(p, s, 'passed', 2))
        worker.enqueue = Mock()
        with patch.object(studio, 'story_stale', return_value=False), \
             patch.object(studio, 'plan_usable', return_value=True), \
             patch.object(studio, 'duration', return_value=3.0):
            worker._run_video({'project':project['id'], 'shot':shot['id']}, lambda _: None)
        self.assertEqual(shot['keyframe'], 'prior_last.png')
        self.assertTrue(shot['video'])

    def test_changed_shot_or_director_selection_cannot_be_overwritten(self):
        for edit in ('staging', 'selection', 'approval'):
            with self.subTest(edit=edit):
                worker, project, shot = self.harness()
                # load() exposes the mutable saved project, so preserve the input snapshot.
                input_project = copy.deepcopy(project)
                input_shot = input_project['shots'][0]
                def change(*_args, **_kwargs):
                    if edit == 'staging':
                        shot['start_frame'] = 'A new direction'
                    elif edit == 'selection':
                        shot['keyframe'] = 'director.png'
                    else:
                        shot['takes']['keyframe'].append({'name':'director.png','review':{'director_review':{'reason':'chosen'}}})
                        shot['keyframe'] = 'director.png'
                    return image_review(input_project, input_shot)
                worker._review_image = Mock(side_effect=change)
                with self.assertRaisesRegex(RuntimeError, 'changed'):
                    self.recover(worker, input_project, input_shot, cast_review())
                worker._render_checked.assert_not_called()
                self.assertIn('original.png', [t['name'] for t in shot['takes']['keyframe']])

    def test_approved_director_take_is_not_replaced_by_automatic_recovery(self):
        worker, project, shot = self.harness()
        shot['keyframe'] = 'chosen.png'
        shot['takes']['keyframe'].append({'name':'chosen.png','review':{'director_review':{'reason':'chosen'}}})
        worker._review_image = Mock()
        name, _, _, _, attempted = self.recover(worker, project, shot, cast_review())
        self.assertEqual(name, 'original.png')
        self.assertFalse(attempted)
        worker._review_image.assert_not_called()
        worker._render_checked.assert_not_called()

    def test_final_promotion_rechecks_staging_and_director_choice_atomically(self):
        for mode in ('draft', 'strict'):
            with self.subTest(mode=mode):
                worker, project, shot = self.harness(mode)
                input_project = copy.deepcopy(project)
                input_shot = input_project['shots'][0]
                review = image_review(input_project, input_shot, 'passed', 2)
                shot['keyframe'] = 'director.png'
                shot['takes']['keyframe'].append({'name':'director.png',
                    'review':{'director_review':{'reason':'chosen'}}})
                with self.assertRaisesRegex(RuntimeError, 'changed before selection'):
                    worker._finish_keyframe(input_project, input_shot, 'alternate.png', 'prompt', 1, {},
                                            lambda _: None, {}, 1, known_review=review, allow_repair=False)
                self.assertEqual(shot['keyframe'], 'director.png')
                self.assertIn('alternate.png', [t['name'] for t in shot['takes']['keyframe']])

    def test_linked_frame_without_recovery_keeps_intervening_director_edits(self):
        for edit in ('staging', 'selection', 'approval'):
            with self.subTest(edit=edit):
                worker, project, shot = self.harness()
                shot['keyframe'] = 'old.png'
                shot['takes']['keyframe'].append({'name': 'old.png', 'review': {}})
                snapshot = copy.deepcopy(project)
                if edit == 'staging':
                    shot['start_frame'] = 'A different viewpoint'
                elif edit == 'selection':
                    shot['keyframe'] = 'director.png'
                    shot['takes']['keyframe'].append({'name': 'director.png', 'review': {}})
                else:
                    shot['takes']['keyframe'][0]['review']['director_review'] = {'reason': 'chosen'}
                with self.assertRaisesRegex(RuntimeError, 'changed before selection'):
                    worker._finish_keyframe(snapshot, snapshot['shots'][0], 'generated.png', 'prompt', 1,
                        {'kind':'shot', 'frame_source':'previous_end'}, lambda _: None, {}, 0)
                self.assertEqual(shot['keyframe'], 'director.png' if edit == 'selection' else 'old.png')
                self.assertIn('generated.png', [t['name'] for t in shot['takes']['keyframe']])

    def test_flagged_recovery_does_not_replace_an_existing_selected_take(self):
        for mode in ('draft', 'strict'):
            with self.subTest(mode=mode):
                worker, project, shot = self.harness(mode)
                shot['keyframe'] = 'chosen.png'
                shot['takes']['keyframe'].append({'name':'chosen.png', 'review':{'status':'needs_review'}})
                snapshot = copy.deepcopy(project)
                review = image_review(snapshot, snapshot['shots'][0], 'extra', 3)
                with self.assertRaisesRegex(RuntimeError, 'earlier selected take was kept'):
                    worker._finish_keyframe(snapshot, snapshot['shots'][0], 'original.png', 'prompt', 1, {},
                                            lambda _: None, {}, 1, known_review=review, allow_repair=False)
                self.assertEqual(shot['keyframe'], 'chosen.png')
                self.assertEqual([t['name'] for t in shot['takes']['keyframe']], ['chosen.png', 'original.png'])


if __name__ == '__main__':
    unittest.main()
