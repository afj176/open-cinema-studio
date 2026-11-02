import copy
import json
import sys
import threading
import unittest
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import studio


def fixture():
    shot = studio.new_shot(action="The lead passes the cup to Tavi", start_frame="Two people, cup in lead's hand",
                           end_state="Tavi holds the cup", beat=1, beat_source="Give Tavi the cup",
                           others="Tavi", keyframe="frame.png", video="clip.mp4", sketch="board.png")
    project = {"id": "scratch", "title": "Test", "scene": "A kitchen", "look": "Paper-cut animation",
               "aspect": "16:9", "cast": "Short black hair", "continuity": "One round ceramic cup",
               "characters": "Tavi: curly hair, green coat", "beats": ["Give Tavi the cup"],
               "reference": "portrait.png", "lead_identity": "Round face and brown eyes",
               "lead_identity_of": "portrait.png", "shots": [shot]}
    project["world"] = {"plate": "world.png", "takes": [{"name": "world.png", "of": studio.world_of(project)}]}
    project["continuity_plan"] = {"of": studio.continuity_inputs(project), "issues": []}
    shot["sketches"] = [{"name": "board.png", "of": studio.sketch_of(shot, None, None, project)}]
    shot["takes"] = {
        "keyframe": [{"name": "frame.png", "recipe": {"kind": "shot", "world": "world.png", "composition_version": 2,
                       "lead": "portrait.png", "sketch": "board.png", "visual": studio.visual_inputs(project, shot)}}],
        "video": [{"name": "clip.mp4", "of": studio.video_inputs(project, shot)}]}
    return project, shot


class AssetDependenciesTests(unittest.TestCase):
    def test_continuation_tracks_previous_video_take(self):
        project, first = fixture()
        second = copy.deepcopy(first)
        second.update(id="continuation", transition="continue", keyframe="seam.png")
        project["shots"].append(second)
        second["takes"]["video"][0]["of"] = studio.video_inputs(project, second)
        self.assertFalse(studio.video_stale(project, second))
        first["video"] = "new_previous_take.mp4"
        self.assertTrue(studio.video_stale(project, second))

    def test_proper_name_selects_the_lead_portrait(self):
        row = 'SHOT: 1 | Mina hands Tavi a cup | Medium | Static | 4 | wind | Mina, Tavi | Mina: "Here" | cut | Mina holds cup | Tavi holds cup'
        shot = studio.director.parse_shots(row, "Mina, a woman with a black bob")[0]
        self.assertTrue(shot["lead"])
        self.assertEqual(shot["others"], "Tavi")
        self.assertEqual(shot["line"], 'Lead: "Here"')

    def test_count_gate_rejects_extra_missing_and_uncertain_people(self):
        folder = Path(__file__).resolve().parents[1] / "custom_nodes/comfyui-open-cinema"
        spec = importlib.util.spec_from_file_location("cast_test_nodes", folder / "__init__.py", submodule_search_locations=[str(folder)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        gate = module.OpenCinemaValidateCast()
        image = object()
        self.assertEqual(gate.validate(image, "2", 2), (image,))
        for answer in ("3", "1", "I cannot tell"):
            with self.assertRaises(ValueError):
                gate.validate(image, answer, 2)
        self.assertEqual(studio.director.character_count(True, "Tavi (green coat)"), 2)
        self.assertIsNone(studio.director.character_count(True, "Crowd (a group of workers)"))

    def test_flagged_count_retains_candidate_without_spending_on_hidden_retries(self):
        obj = object.__new__(studio.Studio)
        class Counter:
            seeds = []
            def submit(self, graph):
                self.seeds.append(graph["sample"]["inputs"]["seed"])
                return "test"
            def wait(self, prompt, **kwargs):
                return {"outputs":{"save":{"images":[{"filename":"candidate.png","type":"output"}]},
                    "cast_review":{"text":[json.dumps({"status":"needs_review","observed_count":3})]}}}
        obj.comfy = Counter()
        result, seed, review = obj._render_checked({"sample": {"inputs": {"seed": 7}}}, 7, lambda _: None)
        self.assertEqual(obj.comfy.seeds, [7])
        self.assertEqual(seed,7)
        self.assertEqual(result[0]['filename'],'candidate.png')
        self.assertEqual(review['status'],'needs_review')

    def test_animal_cast_count_is_used_by_sketch_and_visual_reviews(self):
        prompt = studio.director.CAST_COUNT_CHECK
        self.assertIn('animals', prompt)
        self.assertIn('quadrupeds', prompt)
        self.assertIn('do not count objects', prompt)
        sketch = studio.graphs.storyboard_graph('A cat crosses a field', 7, '16:9', 'test', expected_cast=1)
        review = studio.graphs.visual_review_graph('frame.png', '{}', '2D cartoon')
        self.assertEqual(sketch['count']['inputs']['prompt'], prompt)
        self.assertEqual(review['count']['inputs']['prompt'], prompt)

    def test_reviewer_and_cast_gate_are_in_shared_graphs(self):
        graph = studio.graphs.shot_writer_graph("board", "", "", "", "", "Mina, dark bob", "", "")
        self.assertEqual(graph["4"]["inputs"]["text"], ["review", 0])
        self.assertEqual(graph["4"]["inputs"]["lead_description"], "Mina, dark bob")
        board = studio.graphs.storyboard_graph("Test", 7, "16:9", "scratch", expected_cast=2)
        self.assertEqual(board["11"]["inputs"]["images"], ["mono", 0])
        self.assertEqual(board["cast_review"]["inputs"]["source"], ["checked", 0])
        self.assertEqual(board["checked"]["inputs"]["expected"], 2)

    def test_staging_changes_redraw_frame_and_video(self):
        p, s = fixture()
        self.assertFalse(studio.frame_stale(p, s))
        self.assertFalse(studio.video_stale(p, s))
        self.assertFalse(studio.sketch_stale(p, s))
        s["start_frame"] = "Hands and cup fill frame"
        self.assertTrue(studio.frame_stale(p, s))
        self.assertTrue(studio.video_stale(p, s))
        self.assertTrue(studio.sketch_stale(p, s))

    def test_sound_dialogue_duration_and_outcome_only_rerender_video(self):
        for key, value in (("sound", "Rain"), ("line", 'Tavi: "Thank you"'), ("seconds", 8),
                           ("end_state", "Tavi drinks from the cup")):
            p, s = fixture()
            s[key] = value
            with self.subTest(field=key):
                self.assertFalse(studio.frame_stale(p, s))
                self.assertTrue(studio.video_stale(p, s))

    def test_cast_continuity_medium_and_supporting_cast_invalidate_visuals(self):
        for key, value in (("characters", "Tavi: silver hair, blue jacket"), ("cast", "Red hair"),
                           ("continuity", "A square cup"), ("look", "2D ink animation"),
                           ("scene", "A train"), ("aspect", "9:16")):
            p, s = fixture()
            p[key] = value
            with self.subTest(field=key):
                self.assertTrue(studio.frame_stale(p, s))
                self.assertTrue(studio.sketch_stale(p, s))

    def test_unrelated_supporting_character_does_not_invalidate(self):
        p, s = fixture()
        p["characters"] += "\nSam: red hair"
        self.assertFalse(studio.frame_stale(p, s))

    def test_render_queue_rebuilds_only_video_for_sound_change(self):
        p, s = fixture()
        s["sound"] = "Wind"
        studio_instance = object.__new__(studio.Studio)
        studio_instance.lock = threading.RLock()
        studio_instance.jobs = []
        studio_instance.load = lambda _: copy.deepcopy(p)
        def enqueue(kind, project, shot=None, label="", **kwargs):
            job = {"kind": kind, "project": project, "shot": shot, "state": "queued"}
            studio_instance.jobs.append(job)
            return job
        studio_instance.enqueue = enqueue
        jobs = studio_instance.queue_film("scratch")
        self.assertEqual([j["kind"] for j in jobs], ["video", "stitch"])
        p["beats"][0] = "Keep the cup"
        with self.assertRaisesRegex(RuntimeError, "Story beats changed"):
            studio_instance.queue_film("scratch")

    def test_named_participant_cannot_be_lost_when_who_field_omits_them(self):
        p, s = fixture()
        s["others"] = ""
        self.assertIn("Tavi (curly hair, green coat)", studio.others_in(p, s))

    def test_staging_parser_roundtrip_and_legacy_rows(self):
        _, shot = fixture()
        result = studio.director.parse_shots("SHOT: " + studio.director.shot_line(shot))[0]
        self.assertEqual(result["start_frame"], shot["start_frame"])
        self.assertEqual(result["end_state"], shot["end_state"])
        old = studio.director.parse_shots("SHOT: 1 | The lead opens the door | Wide | Static | 4 | wind | lead | - | cut")[0]
        self.assertEqual(old["start_frame"], "")
        self.assertEqual(old["line"], "")

    def test_storyboard_is_independent_and_monochrome_by_construction(self):
        graph = studio.graphs.storyboard_graph("Test", 7, "16:9", "scratch")
        self.assertNotIn("LoadImage", [n["class_type"] for n in graph.values()])
        self.assertEqual(graph["mono"]["class_type"], "OpenCinemaMonochrome")
        self.assertEqual(graph["11"]["inputs"]["images"], ["mono", 0])
        prompt = studio.director.shot_prompt("Pass a cup", "Medium", "Paper-cut animation", has_cast=True, storyboard=True)
        self.assertIn("storyboard in Picture 1", prompt)
        self.assertIn("Picture 3 is only a materials", prompt)
        tight = studio.director.shot_prompt("Pass a cup", "Medium", "Paper-cut animation", has_cast=True,
                                            storyboard=True, world_reference=False, world="Huge landscape")
        self.assertNotIn("Picture 3", tight)
        self.assertNotIn("Huge landscape", tight)

    def test_paper_cut_medium_wins_over_motion_adjective(self):
        look = "2D paper-cut animation with stop-motion-like movement"
        self.assertEqual(studio.director.medium(look), "papercut")
        self.assertIn("Flat cut-paper pieces", studio.director.motion_prompt("Walk", "Static", look=look))


if __name__ == "__main__":
    unittest.main()
