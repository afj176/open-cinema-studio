import copy
import json
import threading
import unittest
from unittest.mock import Mock

from test_asset_dependencies import fixture
import studio


class ContinuityTests(unittest.TestCase):
    def film(self):
        project, first = fixture()
        project["scene_state"] = {"Cup · held by": "Lead", "Cup · contents": "empty"}
        first.update(state_changes={"Cup · held by": "Tavi"}, start_cast=["Lead", "Tavi"], end_cast=["Lead", "Tavi"],
                     start_checks=["Cup · held by"], end_checks=["Cup · held by"])
        second = copy.deepcopy(first)
        second.update(id="second", state_changes={"Cup · contents": "tea"})
        project["shots"].append(second)
        project["continuity_plan"]["of"] = studio.continuity_inputs(project)
        return project, first, second

    def fake_studio(self, project):
        instance = object.__new__(studio.Studio)
        instance.lock = threading.RLock()
        instance.load = lambda _: copy.deepcopy(project)
        def save(value):
            project.clear()
            project.update(copy.deepcopy(value))
            return value
        instance.save = save
        return instance

    def test_cast_uncertainty_remains_until_director_accepts_plan(self):
        project, first, _ = self.film()
        first['cast_roster_unresolved'] = ['Tavi']
        project['continuity_plan']['issues'] = ['Shot 1: check cast']
        project['continuity_rev'] = 3
        worker = self.fake_studio(project)
        worker.update(project['id'], {'continuity_rev':3, 'title':'Edited title'})
        self.assertEqual(project['shots'][0]['cast_roster_unresolved'], ['Tavi'])
        worker.update(project['id'], {'continuity_rev':3, 'accept_continuity':True})
        self.assertNotIn('cast_roster_unresolved', project['shots'][0])
        self.assertTrue(project['continuity_plan']['acknowledged'])

    def test_ambiguous_presence_review_explains_actual_uncertainty(self):
        project, first, _ = self.film()
        first['cast_roster_unresolved'] = ['Tavi']
        worker = self.fake_studio(project)
        worker._checked_review = Mock(return_value=studio.director.review_result([]))
        result = worker._review_image(project, first, 'frame.png', lambda _: None)
        issue = next(issue for issue in result['issues'] if issue['code'] == 'unresolved_cast_presence')
        self.assertIn('whether this character is visible', issue['message'])

    def test_ledger_inherits_result_and_edit_invalidates_downstream(self):
        project, first, second = self.film()
        self.assertEqual(studio.shot_states(project, second)[0]["Cup · held by"], "Tavi")
        old = studio.visual_inputs(project, second)
        first["state_changes"]["Cup · held by"] = "Lead"
        self.assertNotEqual(old, studio.visual_inputs(project, second))
        self.assertEqual(studio.shot_states(project, second)[1]["Cup · contents"], "tea")
        self.assertEqual(project["scene_state"]["Cup · contents"], "empty")

    def test_ending_change_does_not_change_own_opening_frame(self):
        project, first, _ = self.film()
        visual, video = studio.visual_inputs(project, first), studio.video_inputs(project, first)
        first["state_changes"]["Cup · held by"] = "Sam"
        self.assertEqual(visual, studio.visual_inputs(project, first))
        self.assertNotEqual(video, studio.video_inputs(project, first))

    def test_offscreen_state_does_not_introduce_another_character(self):
        prompt = studio.director.state_direction({"Cup · contents": "empty", "Tavi · possession": "none"},
                                                 visible_keys=["Cup · contents"])
        self.assertNotIn("Tavi", prompt)
        self.assertIn("empty", prompt)

    def test_middle_checks_only_invariants_and_bounds_entrance_count(self):
        project, first, _ = self.film()
        first.update(start_cast=["Lead"], end_cast=["Lead", "Tavi"],
                     start_checks=["Cup · held by", "Cup · contents"], end_checks=["Cup · held by", "Cup · contents"])
        middle = studio.review_requirements(project, first, "middle")
        self.assertEqual(middle["state"], {"Cup · contents": "empty"})
        self.assertEqual(middle["allowed_counts"], [1, 2])
        self.assertEqual(studio.starting_cast(project, first), (True, ""))

    def test_group_rosters_preserve_cast_evidence_without_inventing_a_count(self):
        project, first, _ = self.film()
        project['characters'] = 'The Patrons: a cluster of people in raincoats\nElder Fisher: an older person in grey'
        first.update(start_cast=['Lead', 'Elder Fisher', 'trio of villagers'],
                     end_cast=['Lead', 'Elder Fisher', 'The Patrons'])
        opening = studio.review_requirements(project, first, 'start')
        self.assertEqual(opening['count'], 5)
        self.assertEqual(opening['allowed_counts'], [5])
        self.assertEqual(opening['people']['trio of villagers'], 'trio of villagers')
        self.assertNotIn('trio of villagers', opening['unresolved_cast'])
        ending = studio.review_requirements(project, first, 'end')
        self.assertIsNone(ending['count'])
        self.assertIsNone(ending['allowed_counts'])
        self.assertIn('The Patrons', ending['people'])
        middle = studio.review_requirements(project, first, 'middle')
        self.assertIsNone(middle['allowed_counts'])
        self.assertIn('Elder Fisher', middle['people'])
        self.assertIsNone(studio.director.character_count(True, 'The Patrons (a cluster of people in raincoats)'))
        self.assertEqual(studio.director.character_count(True, 'trio of villagers (three people)'), 4)

    def test_unregistered_proper_name_is_uncertain_not_a_visual_description(self):
        project, first, _ = self.film()
        project['characters'] = 'Tavi: a person in a yellow coat'
        first['start_cast'] = ['Lead', 'Tavi', 'Mara']
        required = studio.review_requirements(project, first, 'start')
        self.assertNotIn('Mara', required['people'])
        self.assertEqual(required['unresolved_cast'], ['Mara'])
        worker = self.fake_studio(project)
        worker._checked_review = Mock(return_value=studio.director.review_result([]))
        result = worker._review_image(project, first, 'frame.png', lambda _: None)
        self.assertEqual(result['outcome'], 'uncertain')
        self.assertTrue(any(issue['code'] == 'unresolved_cast_identity' for issue in result['issues']))

    def test_script_edit_requires_plan_review_but_sound_does_not(self):
        project, first, _ = self.film()
        first["sound"] = "Wind"
        self.assertEqual(studio.plan_status(project), "ready")
        first["action"] = "Keep the cup"
        self.assertEqual(studio.plan_status(project), "stale")

    def report(self):
        return {"count": 2, "style": {"verdict": "pass", "observed": "Flat paper shapes"},
                "cast": {"verdict": "pass", "observed": "Lead and Tavi match wardrobe"},
                "state": [{"key": "Cup · held by", "verdict": "pass", "observed": "Cup in lead's hand"}]}

    def test_vision_parser_rejects_extra_actor_missing_evidence_and_uncertainty(self):
        project, first, _ = self.film()
        expected = json.dumps(studio.review_requirements(project, first, "start"))
        good = self.report()
        self.assertEqual(studio.director.parse_visual_review(json.dumps(good), expected)["status"], "passed")
        for mutate in (lambda r: r.update(count=3), lambda r: r.update(state=[]),
                       lambda r: r["state"][0].update(verdict="uncertain"),
                       lambda r: r["style"].update(verdict="fail"), lambda r: r.update(count=True)):
            bad = copy.deepcopy(good); mutate(bad)
            self.assertEqual(studio.director.parse_visual_review(json.dumps(bad), expected)["status"], "needs_review")
        self.assertEqual(studio.director.parse_visual_review("Not JSON", expected)["status"], "needs_review")

    def test_one_bad_video_sample_fails_entire_clip(self):
        passed = {"version": studio.director.REVIEW_VERSION, "status": "passed", "findings": []}
        reports = [copy.deepcopy(passed) for _ in range(4)]
        self.assertEqual(studio.director.combine_visual_reviews(reports)["status"], "passed")
        reports[2].update(status="needs_review", findings=["Extra person"])
        result = studio.director.combine_visual_reviews(reports)
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("Sample 3: Extra person", result["findings"])
        self.assertEqual(studio.director.combine_visual_reviews([passed])["status"], "needs_review")

    def test_neutral_count_overrides_biased_count_and_survives_bad_schema(self):
        project, first, _ = self.film()
        expected = json.dumps(studio.review_requirements(project, first, "start"))
        report = self.report()
        report["state"][0]["key"] += ": Lead"
        result = studio.director.parse_visual_review(json.dumps(report), expected, "3")
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["evidence"]["reported_count"], 2)
        self.assertTrue(any("observed 3" in finding for finding in result["findings"]))
        self.assertTrue(any("exactly once" in finding for finding in result["findings"]))

    def test_equivalent_keyed_evidence_preserves_verdicts(self):
        project, first, _ = self.film()
        expected = json.dumps(studio.review_requirements(project, first, "start"))
        report = self.report()
        item = report["state"][0]
        report["state"] = {item.pop("key"): item}
        self.assertEqual(studio.director.parse_visual_review(json.dumps(report), expected, "2")["status"], "passed")
        item["verdict"] = "fail"
        self.assertEqual(studio.director.parse_visual_review(json.dumps(report), expected, "2")["status"], "needs_review")

    def test_observation_comparison_can_reject_a_false_pass(self):
        project, first, _ = self.film()
        expected = json.dumps(studio.review_requirements(project, first, "start"))
        report = self.report()
        report["state"][0]["observed"] = "Tavi holds the cup"
        audit = {"state": [{"key": "Cup · held by", "verdict": "fail", "reason": "Tavi holds it, not Lead"}]}
        result = studio.director.parse_visual_review(json.dumps(report), expected, "2", json.dumps(audit))
        self.assertEqual(result["status"], "needs_review")
        self.assertIn("Tavi holds it, not Lead", result["findings"][0])
        brief = studio.director.state_evidence_brief(json.dumps(report), expected)
        self.assertIn("Tavi holds the cup", brief)
        self.assertNotIn('"verdict": "pass"', brief)
        self.assertEqual(studio.director.parse_visual_review(json.dumps(report), expected, "2", '{}')["status"], "needs_review")

    def test_old_autosave_cannot_replace_newly_planned_state(self):
        project, first, _ = self.film()
        project["continuity_rev"] = 2
        instance = self.fake_studio(project)
        old = copy.deepcopy(project)
        old.update(continuity_rev=1, scene_state={"old fact": "old value"})
        old["shots"][0].update(state_changes={}, start_checks=[], start_cast=[])
        instance.update(project["id"], old)
        self.assertIn("Cup · held by", project["scene_state"])
        self.assertEqual(project["shots"][0]["start_cast"], ["Lead", "Tavi"])

    def test_rejected_candidate_is_preserved_without_promotion(self):
        project, first, _ = self.film()
        project['review_policy'] = 'strict'
        instance = self.fake_studio(project)
        review = {"status": "needs_review", "version": 1, "findings": ["Wrong owner"], "of": studio.visual_inputs(project, first)}
        with self.assertRaisesRegex(RuntimeError, "Wrong owner"):
            instance._record_candidate(project["id"], first["id"], "keyframe", "rejected.png", review)
        current = project["shots"][0]
        self.assertEqual(current["keyframe"], "frame.png")
        self.assertEqual(current["video"], "clip.mp4")
        self.assertEqual(current["takes"]["keyframe"][-1]["name"], "rejected.png")
        with self.assertRaisesRegex(RuntimeError, "failed visual review"):
            studio.select_take(current, "keyframe", "rejected.png")

    def test_director_override_requires_reason_and_current_inputs(self):
        project, first, _ = self.film()
        project['review_policy'] = 'strict'
        review = {"status": "needs_review", "version": 1, "findings": ["Ambiguous style"], "of": studio.visual_inputs(project, first)}
        first["takes"]["keyframe"].append({"name": "candidate.png", "review": review})
        instance = self.fake_studio(project)
        with self.assertRaises(ValueError):
            instance.accept_review(project["id"], first["id"], "keyframe", "candidate.png", "")
        instance.accept_review(project["id"], first["id"], "keyframe", "candidate.png", "Inspected cut edges and actor identity")
        take = studio.current_take(project["shots"][0], "keyframe")
        self.assertEqual(take["review"]["automated_status"], "needs_review")
        self.assertTrue(studio.review_passed(take))
        project["scene_state"]["Cup · held by"] = "Tavi"
        with self.assertRaisesRegex(RuntimeError, "out of date"):
            instance.accept_review(project["id"], first["id"], "keyframe", "candidate.png", "Previously inspected")

    def test_stitch_rejects_unreviewed_clips(self):
        project, _, _ = self.film()
        project['review_policy'] = 'strict'
        instance = self.fake_studio(project)
        with self.assertRaisesRegex(RuntimeError, "passing video review"):
            instance._run_stitch({"project": project["id"]}, lambda _: None)

    def test_plan_parser_rejects_missing_rows_and_unknown_state_keys(self):
        plan = {"design": "Round paper cup", "initial": {"owner": "Lead"}, "issues": [],
                "shots": [{"index": 1, "changes": {"owner": "Tavi"}, "start_checks": ["owner"],
                           "end_checks": ["owner"], "start_cast": ["Lead", "Tavi"], "end_cast": ["Lead", "Tavi"]}]}
        self.assertEqual(studio.director.parse_continuity(json.dumps(plan), 1)["initial"], {"owner": "Lead"})
        with self.assertRaises(ValueError):
            studio.director.parse_continuity(json.dumps(plan), 2)
        plan["shots"][0]["changes"]["unknown"] = "changed"
        recovered = studio.director.parse_continuity(json.dumps(plan), 1)
        self.assertEqual(recovered['initial']['unknown'], 'Unknown before first change')
        self.assertEqual(recovered['shots'][0]['changes']['unknown'], 'changed')
        self.assertTrue(any('unknown' in issue for issue in recovered['issues']))
        with self.assertRaises(ValueError):
            studio.director.parse_continuity(json.dumps(plan), 1, recover_missing=False)

    def test_plan_schema_accepts_capitalized_keys_but_rejects_collisions(self):
        plan = {'Initial': {'Location': 'Kitchen'}, 'Design': 'Kitchen', 'Issues': [],
                'Shots': [{'Index': 1, 'Changes': {}, 'start_checks': ['Location'],
                           'end_checks': ['Location'], 'start_cast': ['Lead'], 'end_cast': ['Lead']}]}
        parsed = studio.director.parse_continuity(json.dumps(plan), 1)
        self.assertEqual(parsed['shots'][0]['index'], 1)
        self.assertEqual(parsed['initial'], {'Location': 'Kitchen'})
        plan['Shots'][0]['changes'] = {}
        with self.assertRaisesRegex(ValueError, 'duplicate schema keys'):
            studio.director.parse_continuity(json.dumps(plan), 1)

    def test_video_graph_uses_four_independent_images_and_shared_parser(self):
        graph = studio.graphs.video_review_graph("clip.mp4", "{}", "{}", "{}", "Paper-cut")
        self.assertEqual([graph[f"{i}vision"]["inputs"]["image"] for i in range(4)], [["samples", i] for i in range(4)])
        self.assertEqual(graph["combined"]["class_type"], "OpenCinemaCombineReviews")

    def test_missing_initial_value_requires_review_without_inventing_earlier_state(self):
        plan = {'design':'farm','initial':{'Basket':'empty'},'issues':[], 'shots':[
            {'index':1,'changes':{'Gaze':'fixed on berries'},'start_checks':['Gaze'],
             'end_checks':['Gaze'],'start_cast':['Lead'],'end_cast':['Lead']},
            {'index':2,'changes':{'Net':'covering badger'},'start_checks':['Gaze','Net'],
             'end_checks':['Net'],'start_cast':['Lead'],'end_cast':['Lead']}]}
        recovered = studio.director.parse_continuity(json.dumps(plan), 2)
        self.assertEqual(recovered['initial']['Net'], 'Unknown before first change')
        self.assertEqual(recovered['shots'][0]['start_checks'], [])
        self.assertEqual(recovered['shots'][0]['end_checks'], ['Gaze'])
        self.assertEqual(recovered['shots'][1]['start_checks'], ['Gaze'])
        self.assertEqual(recovered['shots'][1]['end_checks'], ['Net'])
        self.assertTrue(any('Net' in issue for issue in recovered['issues']))
        self.assertEqual(recovered, studio.director.parse_continuity(json.dumps(recovered), 2))


if __name__ == "__main__":
    unittest.main()
