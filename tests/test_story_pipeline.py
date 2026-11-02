import copy
import importlib.util
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import studio


class FakeComfy:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.submitted = []

    def submit(self, graph):
        self.submitted.append(graph)
        return len(self.submitted)

    def wait(self, prompt_id, **kwargs):
        return {"outputs": {k: {"text": [v]} for k, v in next(self.replies).items()}}


def harness(replies):
    s = object.__new__(studio.Studio)
    s.lock = threading.RLock()
    s.jobs = []
    s.comfy = FakeComfy(replies)
    project = {"id": "scratch", "title": "Untitled", "scene": "", "look": "Noir", "cast": "",
               "characters": "Old: a character", "beats": [],
               "shots": [{"id": "made", "action": "Existing shot", "keyframe": "old.png"}]}
    saved, queued = [], []
    s.load = lambda _: copy.deepcopy(project)
    s.list_projects = lambda: []
    s.save = lambda p: saved.append(copy.deepcopy(p))
    s.enqueue = lambda *a, **kw: queued.append((a, kw))
    return s, saved, queued


class StoryPipelineTests(unittest.TestCase):
    def test_events_under_characters_are_not_character_descriptions(self):
        fields = studio.director.parse_story(
            "CHARACTERS: none\nA patrol searches the corridor\nThe lead opens the door\nBEATS: One / Two")
        self.assertEqual(fields["characters"], "")
        self.assertEqual(fields["beats"], "One\nTwo")
        fields = studio.director.parse_story("CHARACTERS: Mara: red coat / Crowd: rain-soaked workers")
        self.assertEqual(fields["characters"], "Mara: red coat\nCrowd: rain-soaked workers")

    def test_incomplete_story_gets_beats_before_save(self):
        draft = {"title": "A Film", "logline": "A goal", "world": "A place", "lead": "A person"}
        s, saved, _ = harness([draft, {"beats": "First\nSecond\nThird"}])
        with patch.object(studio.graphs, "story_writer_graph", side_effect=lambda target, *a, **k: {"target": target}):
            s._run_write_story({"project": "scratch", "target": "everything"}, lambda _: None)
        self.assertEqual([g["target"] for g in s.comfy.submitted], ["everything", "beats"])
        self.assertEqual(saved[0]["beats"], ["First", "Second", "Third"])
        self.assertEqual(saved[0]["characters"], "")

    def test_failed_completion_does_not_save_or_queue(self):
        draft = {"title": "A Film", "logline": "A goal", "world": "A place", "lead": "A person"}
        s, saved, queued = harness([draft, {"beats": "Only one"}])
        with patch.object(studio.graphs, "story_writer_graph", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                s._run_write_story({"project": "scratch", "target": "everything"}, lambda _: None)
        self.assertFalse(saved)
        self.assertFalse(queued)

    def test_storyboard_prompts_allow_additional_people_and_locations(self):
        p = studio.director.sketch_prompt("A guard stops the lead at an archive door", "Medium", has_cast=True,
                                         lead=True, others="Guard (red coat)")
        self.assertIn("Guard (red coat)", p)
        self.assertNotIn("only person", p)
        p = studio.director.shot_prompt("Inside the archive, the lead opens a terminal", "Medium", "Noir")
        self.assertIn("specific location", p)
        self.assertNotIn("in this exact place", p)

    def test_incomplete_shot_coverage_does_not_replace_board(self):
        s, saved, _ = harness([{"shots": '[{"beat": 1, "action": "A door opens"}]'}])
        project = s.load("scratch")
        project["beats"] = ["First", "Second"]
        project["shots"] = [{"id": "blank", "action": "", "keyframe": None}]
        s.load = lambda _: copy.deepcopy(project)
        with patch.object(studio.graphs, "shot_writer_graph", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "cover each requested beat"):
                s._run_write_shots({"project": "scratch", "mode": "board"}, lambda _: None)
        self.assertFalse(saved)

    def test_blank_spark_varies_but_directors_idea_is_not_redirected(self):
        first = studio.director.story_brief("everything", title="Untitled film", creative_seed=17)
        second = studio.director.story_brief("everything", title="Untitled film", creative_seed=83)
        self.assertNotEqual(first, second)
        self.assertNotIn("Title: Untitled film", first)
        idea = studio.director.story_brief("everything", idea="A botanist studies an alien ocean", creative_seed=17)
        self.assertIn("A botanist studies an alien ocean", idea)
        self.assertNotIn("For this blank spark", idea)

    def test_freeform_look_flows_to_media_and_preserves_medium(self):
        look = "2D animation, hand-painted ink washes and a pale ochre sky"
        self.assertEqual(studio.director.parse_story("LOOK: " + look)["look"], look)
        self.assertEqual(studio.director.medium(look), "illustration")
        self.assertEqual(studio.director.medium("3D animation, miniature brass creatures"), "cg")
        self.assertEqual(studio.director.medium("Hyper-detailed 3D rendering with soft light"), "cg")
        self.assertEqual(studio.director.medium("stop-motion paper puppets"), "stopmotion")
        self.assertIn(look, studio.director.cast_prompt("A gardener", "A courtyard", look))
        self.assertIn(look, studio.director.world_plate_prompt("A courtyard", look))
        self.assertIn(look, studio.director.shot_prompt("A gardener plants seeds", "Medium", look))
        self.assertIn(look, studio.director.motion_prompt("The gardener plants seeds", "Static", look=look))
        self.assertNotIn("photograph", studio.director.MEDIUM_FRAME[studio.director.medium(look)])

    def test_cartoon_spark_defaults_to_2d_but_explicit_medium_wins(self):
        d = studio.director
        idea = "A colourful cartoon about ninja cats on a farm"
        brief = d.story_brief("everything", idea=idea)
        self.assertIn("hand-drawn or illustrated 2D", brief)
        result = d.parse_story("LOOK: Stylized 3D animation with painterly textures and volumetric lighting.", idea=idea)["look"]
        self.assertEqual(d.medium(result), "illustration")
        self.assertNotIn("3D", result)
        self.assertIn("painterly textures", result)
        self.assertEqual(d.medium("a colourful cartoon"), "illustration")
        self.assertEqual(d.medium("3D cartoon"), "cg")
        for specified in ("a 3D cartoon about cats", "a CGI cartoon", "a claymation cartoon", "a paper-cut cartoon"):
            self.assertEqual(d.parse_story("LOOK: 3D animation with painterly textures", idea=specified)["look"],
                             "3D animation with painterly textures")
        self.assertTrue(d.cartoon_2d_default("a cartoon, not 3D"))
        self.assertTrue(d.cartoon_2d_default("hand-drawn cartoon with a 3D camera"))
        self.assertIn("3D camera", d.cartoon_look("3D camera with painted animation", "hand-drawn cartoon with a 3D camera"))
        self.assertFalse(d.cartoon_2d_default("hand-drawn paper-cut cartoon"))
        self.assertFalse(d.cartoon_2d_default("a mixed 2D and 3D cartoon"))
        self.assertEqual(d.medium("a cartoon in 3D"), "cg")
        self.assertEqual(d.medium("2D hand-drawn cartoon with a 3D background"), "illustration")
        self.assertEqual(d.medium("cartoon without 3D"), "illustration")
        no_3d = d.parse_story("LOOK: Hand-painted cartoon, no 3D rendering", idea=idea)["look"]
        self.assertNotIn("no 2D", no_3d)
        graph = studio.graphs.story_writer_graph("everything", idea, "", "", "", "", "")
        self.assertEqual(graph['4']['inputs']['idea'], ['2', 1])

    def test_2d_cartoon_coverage_keeps_flat_animal_character_identity(self):
        d = studio.director
        prompt = d.shot_prompt("The cat reaches for a berry", "Medium", "Hand-drawn 2D cartoon, bright colours",
                               has_cast=True, storyboard=True, lead=True, cast="A ginger tabby cat")
        self.assertIn("flat hand-drawn 2D cartoon artwork", prompt)
        self.assertIn("same species, face, distinctive markings", prompt)
        self.assertNotIn("person from Picture 2", prompt)
        self.assertNotIn("skin tone, hair", prompt)
        self.assertIn("single character", d.cast_prompt("A cat", "A farm", "2D cartoon"))
        for look in ("watercolor illustration", "paper-cut animation", "3D cartoon", "mixed 2D and 3D cartoon"):
            self.assertEqual(d.cartoon_render_direction(look), "")

    def test_look_rewrite_keeps_graphics_colours(self):
        s, saved, _ = harness([{"look": "2D animation, ink on paper"}])
        with patch.object(studio.graphs, "story_writer_graph", return_value={}):
            s._run_write_story({"project": "scratch", "target": "look"}, lambda _: None)
        self.assertEqual(saved[0]["look"], "2D animation, ink on paper")
        self.assertEqual(saved[0]["palette"]["bg"], studio.director.LOOK_PALETTES["Noir"][3])

    def test_repeated_title_words_are_derived_from_local_films(self):
        films = [{"title": "Echoes of Glass Cities"}, {"title": "Echoes of Silicon Dawn"},
                 {"title": "A Glass Garden"}]
        words = studio.repeated_title_words(films)
        self.assertIn("echo", words)
        self.assertIn("glass", words)
        self.assertNotIn("cities", words)
        brief = studio.director.story_brief("everything", creative_seed=17, avoid_title_words=words)
        self.assertIn("Avoid these repeated title words", brief)
        explicit = studio.director.story_brief("everything", idea="A story called Echo", avoid_title_words=words)
        self.assertIn("unless explicitly present", explicit)

    def test_title_selection_rejects_recurring_words_for_typed_ideas(self):
        candidates = '["Echo Bloom Academy", "Echoes Rising", "The Restraint Test"]'
        self.assertEqual(studio.director.select_title(candidates, "echo, glass", "a school for mutants"), "The Restraint Test")
        self.assertEqual(studio.director.select_title(candidates, "echo", "A school called Echo Bloom Academy"), "Echo Bloom Academy")
        with self.assertRaises(ValueError):
            studio.director.select_title('["Echo School"]', "echo", "a school for mutants")
        self.assertEqual(studio.repeated_title_words([{"title":"Scratch - paper test"}]*4), "")

    def test_freeform_look_is_accepted_by_lead_and_motion_nodes(self):
        folder = ROOT / "custom_nodes" / "comfyui-open-cinema"
        spec = importlib.util.spec_from_file_location("open_cinema_test", folder / "__init__.py",
                                                      submodule_search_locations=[str(folder)])
        nodes = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = nodes
        spec.loader.exec_module(nodes)
        for name in ("OpenCinemaLeadBrief", "OpenCinemaTitleOverlay", "OpenCinemaShotStamp", "OpenCinemaCards",
                     "OpenCinemaTitlePreview", "OpenCinemaTypeSheet"):
            with self.subTest(node=name):
                self.assertEqual(getattr(nodes, name).INPUT_TYPES()["required"]["look"][0], "STRING")

    def test_stylized_identity_does_not_become_model_commentary(self):
        self.assertFalse(studio.usable_identity("This request asks me to describe a person based on a provided image"))
        self.assertFalse(studio.usable_identity("I cannot describe this image"))
        self.assertTrue(studio.usable_identity("Round face, dark brown bob, wide brown eyes"))
        self.assertIn("regardless of medium", studio.director.lead_brief("identity", "", "", "2D animation"))


if __name__ == "__main__":
    unittest.main()
