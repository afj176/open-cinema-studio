"""World plates retain uncertain evidence and allow a director to choose a candidate."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from test_asset_dependencies import fixture
import studio
from comfy import ComfyError


class WorldReviewTests(unittest.TestCase):
    def test_planner_extracts_optional_fragments_without_rejecting_legacy_or_malformed_output(self):
        plan = {'design':'A station', 'initial':{}, 'shots':[{'index':1, 'changes':{},
                'start_checks':[], 'end_checks':[], 'start_cast':[], 'end_cast':[]}], 'issues':[]}
        plan['environment'] = [' a quiet bus stop ', 'at sunrise']
        self.assertEqual(studio.director.parse_continuity(json.dumps(plan), 1)['environment'],
                         ['a quiet bus stop', 'at sunrise'])
        for value in (None, 'not a list', [''], [42], ['x' * 301], ['x'] * 21):
            plan['environment'] = value
            self.assertEqual(studio.director.parse_continuity(json.dumps(plan), 1)['environment'], [])
        self.assertIn('each phrase must occur verbatim', studio.director.continuity_brief('{}'))

    def harness(self, answers, policy='draft'):
        project, _ = fixture()
        project.update(review_policy=policy, world={})
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.load = lambda _: copy.deepcopy(project)
        def save(value):
            project.clear()
            project.update(copy.deepcopy(value))
            return value
        worker.save = save
        worker.path = Mock(return_value=__import__('pathlib').Path('.'))
        worker._upload = Mock(return_value='world.png')
        worker.comfy = Mock()
        worker.comfy.run.return_value = [{'filename':'result.png'}]
        worker.comfy.submit.return_value = 'prompt'
        worker.comfy.wait.side_effect = [
            answer if isinstance(answer, Exception) else {'outputs':{'answer':{'text':[answer]}}}
            for answer in answers]
        return worker, project

    def test_inconclusive_draft_is_kept_with_unknown_evidence_without_retry(self):
        for answer in ('UNCERTAIN', '', 'Maybe no people', 'NO, I am not sure'):
            with self.subTest(answer=answer):
                worker, project = self.harness([answer])
                name = worker._make_world('scratch', lambda _: None)
                self.assertEqual(worker.comfy.run.call_count, 1)
                self.assertEqual(project['world']['plate'], name)
                self.assertIsNone(project['world']['takes'][-1]['empty'])
                self.assertEqual(studio.current_plate(project), name)

    def test_strict_uncertain_candidate_is_saved_and_can_be_explicitly_selected(self):
        worker, project = self.harness(['UNCERTAIN'], policy='strict')
        with self.assertRaisesRegex(RuntimeError, 'needs review.*inconclusive'):
            worker._make_world('scratch', lambda _: None)
        take = project['world']['takes'][-1]
        self.assertIsNone(take['empty'])
        self.assertIsNone(studio.current_plate(project))
        worker.choose_world('scratch', take['name'])
        self.assertEqual(studio.current_plate(project), take['name'])
        self.assertIsNone(project['world']['takes'][-1]['empty'])

    def test_yes_is_bounded_to_three_generations_and_strict_saves_without_selecting(self):
        worker, project = self.harness(['YES', 'YES', 'YES'], policy='strict')
        with self.assertRaisesRegex(RuntimeError, 'needs review.*three attempts'):
            worker._make_world('scratch', lambda _: None)
        self.assertEqual(worker.comfy.run.call_count, 3)
        self.assertFalse(project['world']['takes'][-1]['empty'])
        self.assertIsNone(studio.current_plate(project))

    def test_clean_result_after_retry_is_selected_in_strict(self):
        worker, project = self.harness(['YES', 'NO.'], policy='strict')
        name = worker._make_world('scratch', lambda _: None)
        self.assertEqual(worker.comfy.run.call_count, 2)
        self.assertIs(project['world']['takes'][-1]['empty'], True)
        self.assertEqual(studio.current_plate(project), name)

    def test_review_failure_is_uncertain_but_user_interrupt_is_not_swallowed(self):
        worker, project = self.harness([RuntimeError('review failed')])
        worker._make_world('scratch', lambda _: None)
        self.assertIsNone(project['world']['takes'][-1]['empty'])
        worker, project = self.harness([ComfyError('execution interrupted')])
        with self.assertRaisesRegex(ComfyError, 'interrupted'):
            worker._make_world('scratch', lambda _: None)
        self.assertFalse(project['world'])

    def test_world_edits_during_generation_do_not_select_stale_plate(self):
        worker, project = self.harness(['NO'])
        def change_world(*args, **kwargs):
            project['scene'] = 'A different location'
            return {'outputs':{'answer':{'text':['NO']}}}
        worker.comfy.wait.side_effect = change_world
        with self.assertRaisesRegex(RuntimeError, 'world changed'):
            worker._make_world('scratch', lambda _: None)
        self.assertIsNone(studio.current_plate(project))
        self.assertEqual(len(project['world']['takes']), 1)

    def test_current_verbatim_environment_replaces_character_action_in_plate_prompt(self):
        worker, project = self.harness(['NO'])
        project['scene'] = 'Mira waits with Tavi at a quiet bus stop at sunrise, beside red brick buildings.'
        project['cast'] = 'Mira, dark hair and a green jacket'
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        project['continuity_plan']['environment'] = ['a quiet bus stop at sunrise', 'red brick buildings']
        name = worker._make_world('scratch', lambda _: None)
        take = project['world']['takes'][-1]
        self.assertEqual(take['of']['environment'], ['a quiet bus stop at sunrise', 'red brick buildings'])
        self.assertIn('a quiet bus stop at sunrise', take['prompt'])
        self.assertIn('red brick buildings', take['prompt'])
        self.assertNotIn('Mira waits', take['prompt'])
        self.assertEqual(studio.current_plate(project), name)

    def test_environment_extraction_falls_back_on_stale_invented_or_cast_fragments(self):
        project, _ = fixture()
        project['scene'] = 'Mira and Tavi wait at a blue station in the rain.'
        project['cast'] = 'Mira, dark hair'
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        for fragments in (['a red station'], ['Mira and Tavi'], [], ['a blue station', 'invented detail']):
            with self.subTest(fragments=fragments):
                project['continuity_plan']['environment'] = fragments
                self.assertEqual(studio.world_environment(project), [])
                self.assertEqual(studio.world_plate_inputs(project), {**studio.world_of(project), 'environment': []})
        project['continuity_plan']['environment'] = ['a blue station', 'in the rain']
        self.assertEqual(studio.world_environment(project), ['a blue station', 'in the rain'])
        project['continuity_plan']['of']['scene'] = 'An obsolete scene'
        self.assertEqual(studio.world_environment(project), [])

    def test_extraction_lineage_invalidates_new_takes_when_direction_changes_but_keeps_legacy(self):
        project, _ = fixture()
        project['scene'] = 'A blue station in the rain, under a clock.'
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        project['continuity_plan']['environment'] = ['A blue station', 'in the rain']
        new = {'name':'new.png', 'of':studio.world_plate_inputs(project)}
        old = {'name':'old.png', 'of':studio.world_of(project)}
        project['world'] = {'plate':'new.png', 'takes':[new, old]}
        self.assertEqual(studio.current_plate(project), 'new.png')
        project['shots'][0]['action'] = 'A different shot action'
        self.assertEqual(studio.current_plate(project), 'new.png')
        project['continuity_plan']['environment'] = ['A blue station', 'under a clock']
        self.assertIsNone(studio.current_plate(project))
        project['world']['plate'] = 'old.png'
        self.assertEqual(studio.current_plate(project), 'old.png')

    def test_new_fallback_plate_becomes_stale_when_extraction_is_later_available(self):
        worker, project = self.harness(['NO'])
        project['scene'] = 'Mira waits at a blue station in the rain.'
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        project['continuity_plan']['environment'] = []
        name = worker._make_world('scratch', lambda _: None)
        fallback = project['world']['takes'][-1]
        self.assertEqual(fallback['of']['environment'], [])
        self.assertEqual(studio.current_plate(project), name)
        project['continuity_plan']['environment'] = ['a blue station', 'in the rain']
        self.assertIsNone(studio.current_plate(project))

        # A pre-extraction plate has no marker and retains legacy compatibility.
        project['world']['takes'].append({'name': 'legacy.png', 'of': studio.world_of(project)})
        project['world']['plate'] = 'legacy.png'
        self.assertEqual(studio.current_plate(project), 'legacy.png')

    def test_replanning_during_plate_render_keeps_unselected_old_candidate(self):
        worker, project = self.harness(['NO'])
        project['scene'] = 'A blue station in the rain, under a clock.'
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        project['continuity_plan']['environment'] = ['A blue station', 'in the rain']
        def change_environment(*args, **kwargs):
            project['continuity_plan']['environment'] = ['A blue station', 'under a clock']
            return {'outputs':{'answer':{'text':['NO']}}}
        worker.comfy.wait.side_effect = change_environment
        with self.assertRaisesRegex(RuntimeError, 'world changed'):
            worker._make_world('scratch', lambda _: None)
        self.assertIsNone(studio.current_plate(project))
        self.assertEqual(len(project['world']['takes']), 1)

    def test_current_world_status_is_computed_for_the_ui_not_persisted(self):
        project, _ = fixture()
        project['scene'] = 'A blue station in the rain.'
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        project['continuity_plan']['environment'] = ['A blue station', 'in the rain']
        project['world'] = {'plate':'current.png', 'takes':[{'name':'current.png', 'of':studio.world_plate_inputs(project)}]}
        runtime = Path(__file__).resolve().parents[1] / 'runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as folder:
            previous = studio.PROJECTS
            try:
                studio.PROJECTS = Path(folder)
                worker = object.__new__(studio.Studio)
                worker.lock = threading.RLock()
                saved = worker.save(project)
                self.assertTrue(saved['world_plate_current'])
                self.assertNotIn('world_plate_current', json.loads((Path(folder) / 'scratch/project.json').read_text(encoding='utf-8')))
                self.assertTrue(worker.load('scratch')['world_plate_current'])
                project['continuity_plan']['environment'] = ['A blue station']
                self.assertFalse(worker.save(project)['world_plate_current'])
                self.assertFalse(worker.load('scratch')['world_plate_current'])
                project['continuity_plan']['environment'] = []
                project['world']['takes'][0]['of'] = studio.world_plate_inputs(project)
                self.assertTrue(worker.save(project)['world_plate_current'])
                project['continuity_plan']['environment'] = ['A blue station']
                self.assertFalse(worker.save(project)['world_plate_current'])
                self.assertFalse(worker.load('scratch')['world_plate_current'])
            finally:
                studio.PROJECTS = previous


if __name__ == '__main__':
    unittest.main()
