import copy
import threading
import unittest

from test_asset_dependencies import fixture
import studio


class ContinuityAutoFixTests(unittest.TestCase):
    issue = "Shot 1 introduces 'Lead focus' which is not defined in initial state facts."

    def fake(self, issues=None):
        project, _ = fixture()
        project['scene_state'] = {'Bloom':'intact'}
        project['shots'][0]['state_changes'] = {}
        project['continuity_rev'] = 4
        project['continuity_plan']['issues'] = [self.issue] if issues is None else issues
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        obj = object.__new__(studio.Studio)
        obj.lock = threading.RLock()
        obj.jobs = [{'id':'bad-plan','project':'film','kind':'plan_continuity',
                     'state':'needs_review','render_after':True}]
        obj.load = lambda _: copy.deepcopy(project)
        def save(updated):
            project.clear(); project.update(copy.deepcopy(updated)); return copy.deepcopy(updated)
        obj.save = save
        calls=[]
        obj.queue_film=lambda pid: calls.append(pid) or [{'id':'next'}]
        return obj, project, calls

    def test_resolves_only_obsolete_warning_preserving_states_and_resumes(self):
        obj, project, calls = self.fake()
        before = copy.deepcopy(project['scene_state']), copy.deepcopy(project['shots'])
        result = obj.auto_fix_continuity('bad-plan', 4)
        self.assertEqual((project['scene_state'], project['shots']), before)
        self.assertEqual(project['continuity_plan']['issues'], [])
        self.assertEqual(project['continuity_rev'], 5)
        self.assertTrue(result['resumed'])
        self.assertEqual(calls,['film'])

    def test_keeps_other_issues_and_never_resumes(self):
        obj, project, calls = self.fake([self.issue, 'The prop changes owner without an action.'])
        result=obj.auto_fix_continuity('bad-plan',4)
        self.assertEqual(result['remaining'],['The prop changes owner without an action.'])
        self.assertFalse(result['resumed'])
        self.assertEqual(calls,[])

    def test_unknown_initial_value_is_not_silently_accepted(self):
        obj, project, calls = self.fake()
        project['scene_state']['Other fact'] = 'Unknown before first change'
        result = obj.auto_fix_continuity('bad-plan', 4)
        self.assertFalse(result['resumed'])
        self.assertIn('Other fact', result['remaining'][0])
        self.assertEqual(studio.plan_status(project),'issues')
        self.assertEqual(calls,[])

    def test_does_not_remove_warning_if_any_shot_references_the_fact(self):
        obj, project, calls = self.fake()
        project['shots'][0]['state_changes']['Lead focus']='bloom'
        self.assertEqual(studio.continuity_auto_fixes(project),[])
        with self.assertRaisesRegex(ValueError,'No safe automatic fix'):
            obj.auto_fix_continuity('bad-plan',4)
        self.assertEqual(calls,[])

    def test_rejects_stale_plan_or_revision(self):
        obj, project, calls = self.fake()
        with self.assertRaisesRegex(ValueError,'plan changed'):
            obj.auto_fix_continuity('bad-plan',3)
        project['shots'][0]['action'] += ' changed'
        with self.assertRaisesRegex(ValueError,'No safe automatic fix'):
            obj.auto_fix_continuity('bad-plan',4)
        self.assertEqual(calls,[])


if __name__ == '__main__':
    unittest.main()
