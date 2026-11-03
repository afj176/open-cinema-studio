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
    def test_live_action_with_stop_motion_set_does_not_exclude_human_cast(self):
        look = 'Warm live-action photography of a miniature stop-motion workshop'
        self.assertEqual(studio.director.medium(look), 'photo')
        self.assertNotIn('real people', studio.director.image_negative(look))
        portrait = studio.director.cast_prompt('A human puppeteer in a blue shirt', '', look)
        self.assertNotIn('A stop-motion character', portrait)
        self.assertIn('real full-sized living human', portrait)
        self.assertNotIn('miniature stop-motion workshop', portrait)
        puppet = studio.director.cast_prompt('A cloth puppet with a red scarf', '', look)
        self.assertNotIn('real full-sized living human', puppet)
        self.assertEqual(studio.director.medium('stop-motion animation with handmade puppets'), 'stopmotion')
    def test_cast_reconciliation_adds_only_explicit_presence(self):
        worker, saved, _ = harness([])
        project = worker.load('scratch')
        project.update(cast='Rae, a puppeteer', characters='Pip: a cloth puppet\nCrowd: a group of villagers')
        project['shots'] = [studio.new_shot(action='Rae adjusts Pip', start_frame='Rae stands at the table with Pip in front of her')]
        worker.load = lambda _: copy.deepcopy(project)
        worker._text_graph = lambda *args, **kwargs: {'initial':{},'design':'','issues':[],
            'shots':[{'changes':{},'start_checks':[],'end_checks':[],'start_cast':['Rae'],'end_cast':['Rae','Pip']}]}
        worker._run_plan_continuity({'project':'scratch'}, lambda _: None)
        self.assertEqual(saved[-1]['shots'][0]['start_cast'], ['Rae','Pip'])
        self.assertEqual(saved[-1]['continuity_plan']['cast_corrections'], [{'shot':1,'name':'Pip'}])
        self.assertEqual(saved[-1]['continuity_plan']['issues'], [])

    def test_ambiguous_or_contradictory_cast_is_not_counted_as_certain(self):
        for staging, initial in [('Rae waits while Pip enters the doorway', {}),
                                 ('Rae stands at the table with Pip in front of her', {'Pip presence':'absent'})]:
            with self.subTest(staging=staging):
                worker, saved, _ = harness([])
                project = worker.load('scratch')
                project.update(cast='Rae, a puppeteer', characters='Pip: a cloth puppet')
                project['shots'] = [studio.new_shot(action='Rae waits', start_frame=staging)]
                worker.load = lambda _: copy.deepcopy(project)
                worker._text_graph = lambda *args, **kwargs: {'initial':initial,'design':'','issues':[],
                    'shots':[{'changes':{},'start_checks':[],'end_checks':[],'start_cast':['Rae'],'end_cast':['Rae','Pip']}]}
                worker._run_plan_continuity({'project':'scratch'}, lambda _: None)
                result = saved[-1]
                self.assertEqual(result['shots'][0]['start_cast'], ['Rae'])
                self.assertEqual(result['shots'][0]['cast_roster_unresolved'], ['Pip'])
                self.assertIsNone(studio.review_requirements(result, result['shots'][0], 'start')['count'])
                self.assertIn('visible cast is uncertain', result['continuity_plan']['issues'][0])
                before = studio.visual_inputs(result, result['shots'][0])
                confirmed = copy.deepcopy(result)
                confirmed['shots'][0].pop('cast_roster_unresolved')
                self.assertNotEqual(before, studio.visual_inputs(confirmed, confirmed['shots'][0]))
                sketch = studio.director.sketch_prompt('waits', 'Medium', lead=True, start_frame=staging,
                                                       expected_cast=None, cast_uncertain=True)
                frame = studio.director.shot_prompt('waits', 'Medium', 'Noir', lead=True,
                                                     start_frame=staging, cast_uncertain=True)
                self.assertNotIn('Exactly 1 visible', sketch)
                self.assertNotIn('only character', frame)

    def test_offscreen_and_uncountable_groups_are_never_auto_added(self):
        context = {'characters':'Pip: a cloth puppet\nCrowd: a group of villagers',
                   'shots':[{'start_frame':'Rae stands with Pip offscreen and Crowd in front of her'}]}
        plan = {'shots':[{'start_cast':['Rae']}]}
        conflicts = studio.director.cast_roster_conflicts(context, plan)
        self.assertEqual(conflicts, [])

    def test_negated_hypothetical_and_depicted_staging_is_not_auto_corrected(self):
        for staging in ('Rae and Pip stand together, but not in this scene',
                        'If Rae and Pip stand together, use a wide shot',
                        'A painting shows Rae and Pip standing; Rae and Pip stand beside it',
                        'Rae says "Rae and Pip stand together"'):
            with self.subTest(staging=staging):
                context = {'characters':'Pip: a cloth puppet', 'shots':[{'start_frame':staging}]}
                conflicts = studio.director.cast_roster_conflicts(context, {'shots':[{'start_cast':['Rae']}]})
                self.assertEqual(conflicts, [{'index':1, 'name':'Pip', 'explicit':False}])

    def test_named_lead_alias_does_not_generate_false_conflict(self):
        context = {'cast':'Rae, a puppeteer', 'characters':'Pip: a cloth puppet',
                   'shots':[{'start_frame':'Rae and Pip stand by the table'}]}
        plan = {'shots':[{'start_cast':['Lead', 'Pip']}]}
        self.assertEqual(studio.director.cast_roster_conflicts(context, plan), [])
        plan['shots'][0]['start_cast'] = ['Pip']
        self.assertEqual(studio.director.cast_roster_conflicts(context, plan),
                         [{'index':1,'name':'Rae','explicit':True}])

    def test_repair_brief_flags_omission_without_asserting_visibility(self):
        import json
        context = {'characters':'Pip: a cloth puppet', 'shots':[{'start_frame':'Rae stands with Pip in front of her'}]}
        plan = {'initial':{},'design':'','issues':[], 'shots':[{'index':1,'changes':{},
                'start_checks':[],'end_checks':[],'start_cast':['Rae'],'end_cast':['Rae','Pip']}]}
        brief = studio.director.continuity_repair_brief(json.dumps(plan), json.dumps(context), 1)
        self.assertIn('shot 1: Pip', brief)
        self.assertIn('If visibility is unclear, use null', brief)
    def test_dialogue_direction_is_passed_to_the_writer(self):
        graph = studio.graphs.shot_writer_graph("board", "", "", "", "", "", "", "", dialogue_mode="dialogue",
                                                idea='June says "Welcome back."')
        self.assertEqual(graph["2"]["inputs"]["dialogue_mode"], "dialogue")
        self.assertEqual(graph["2"]["inputs"]["idea"], 'June says "Welcome back."')
        auto = studio.director.shot_brief("board")
        spoken = studio.director.shot_brief("board", dialogue_mode="dialogue")
        silent = studio.director.shot_brief("board", dialogue_mode="silent")
        self.assertIn("Let the story, genre, and character relationships decide", auto)
        self.assertNotIn("Most shots have none", auto)
        self.assertIn("alternate speakers across shots", spoken)
        self.assertIn("Always write - for the line field", silent)
        script = studio.director.shot_brief("board", idea='June says "Welcome back."')
        self.assertIn('June says "Welcome back."', script)
        self.assertIn("Respect explicitly requested dialogue", script)

    def test_complete_story_is_saved_and_shots_continue_when_images_are_missing(self):
        draft = {"title":"A Film", "logline":"A goal", "world":"A place", "lead":"A person",
                 "beats":"Opening\nObstacle\nResolution"}
        worker, saved, queued = harness([draft])
        project = worker.load('scratch')
        project['shots'] = [studio.new_shot()]
        worker.load = lambda _: copy.deepcopy(project)
        worker._save_jobs = lambda: None
        def enqueue(kind, *args, **kwargs):
            if kind in ('cast','world'):
                raise RuntimeError('Models are missing: image model. Open Setup to install them.')
            queued.append((kind, args, kwargs))
        worker.enqueue = enqueue
        worker._run_write_story({'project':'scratch','target':'everything'}, lambda _: None)
        self.assertEqual(saved[0]['title'], 'A Film')
        self.assertEqual([job['kind'] for job in worker.jobs], ['cast','world'])
        self.assertTrue(all(job['state']=='blocked' and job['setup_blocked'] for job in worker.jobs))
        self.assertEqual(queued[0][0], 'write_shots')

    def test_planning_saves_state_and_defers_requested_downstream_work(self):
        for auto_render in (True, False):
            with self.subTest(auto_render=auto_render):
                worker, saved, _ = harness([])
                project = worker.load('scratch')
                project['shots'] = [studio.new_shot(action='Walk to the door')]
                worker.load = lambda _: copy.deepcopy(project)
                worker._save_jobs = lambda: None
                worker._text_graph = lambda *args, **kwargs: {'initial':{},'design':'','issues':[],
                    'shots':[{'changes':{},'start_checks':[],'end_checks':[],'start_cast':[],'end_cast':[]}]}
                def missing(*args, **kwargs):
                    raise RuntimeError('Models are missing: video. Open Setup.')
                worker.queue_film = missing
                worker.queue_sketches = missing
                worker._run_plan_continuity({'project':'scratch','render_after':auto_render,'draw_after':True}, lambda _: None)
                self.assertEqual(saved[0]['continuity_plan']['issues'], [])
                self.assertEqual(worker.jobs[-1]['kind'], 'resume_film' if auto_render else 'resume_board')
                self.assertEqual(worker.jobs[-1]['state'], 'blocked')

    def test_invalid_scene_state_retries_once_but_other_failures_do_not(self):
        from unittest.mock import Mock
        worker, saved, _ = harness([])
        project = worker.load('scratch')
        project['shots'] = [studio.new_shot(action='Walk to the door')]
        worker.load = lambda _: copy.deepcopy(project)
        plan = {'initial': {}, 'design': '', 'issues': [], 'shots': [
            {'changes': {}, 'start_checks': [], 'end_checks': [], 'start_cast': [], 'end_cast': []}]}
        worker._metric = Mock()
        worker._text_graph = Mock(side_effect=[studio.ComfyError('Scene state must be an object with at most 32 named facts'), plan])
        worker._run_plan_continuity({'project': 'scratch'}, lambda _: None)
        self.assertEqual(worker._text_graph.call_count, 2)
        retry = worker._text_graph.call_args.args[0]
        self.assertEqual(retry['repair']['inputs']['sampling_mode'], 'on')
        self.assertEqual(saved[-1]['continuity_plan']['issues'], [])
        worker._text_graph = Mock(side_effect=studio.ComfyError('interrupted'))
        with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
            worker._run_plan_continuity({'project': 'scratch'}, lambda _: None)
        self.assertEqual(worker._text_graph.call_count, 1)

    def test_dialogue_direction_persists_and_rejects_invalid_values(self):
        s, saved, _ = harness([])
        s.create({})
        self.assertEqual(saved[-1]["dialogue_mode"], "auto")
        s.update("scratch", {"dialogue_mode": "dialogue"})
        self.assertEqual(saved[-1]["dialogue_mode"], "dialogue")
        with self.assertRaisesRegex(ValueError, "dialogue direction"):
            s.update("scratch", {"dialogue_mode": "unknown"})

    def test_silent_direction_clears_model_written_lines_not_kept_shots(self):
        response = '[{"beat":1,"action":"Lead greets June","line":"Lead: Hello!",' \
                   '"start_frame":"Lead faces June","end_state":"June waves"}]'
        s, saved, _ = harness([{"shots": response}])
        project = s.load("scratch")
        project["dialogue_mode"] = "silent"
        project["idea"] = "A quiet reunion"
        project["beats"] = ["Lead greets June"]
        project["shots"][0]["line"] = "Lead: An existing line"
        s.load = lambda _: copy.deepcopy(project)
        s._run_write_shots({"project": "scratch", "mode": "board"}, lambda _: None)
        self.assertEqual(s.comfy.submitted[0]["2"]["inputs"]["dialogue_mode"], "silent")
        self.assertEqual(s.comfy.submitted[0]["2"]["inputs"]["idea"], "A quiet reunion")
        self.assertEqual(saved[0]["shots"][0]["line"], "Lead: An existing line")
        self.assertEqual(saved[0]["shots"][1]["line"], "")

    def test_dialogue_mode_change_rejects_obsolete_writer_result(self):
        response = '[{"beat":1,"action":"Lead greets June","line":"Lead: Hello!",' \
                   '"start_frame":"Lead faces June","end_state":"June waves"}]'
        s, saved, _ = harness([{"shots": response}])
        before = s.load("scratch")
        before.update(dialogue_mode="auto", beats=["Lead greets June"])
        after = copy.deepcopy(before)
        after["dialogue_mode"] = "silent"
        snapshots = iter([before, after])
        s.load = lambda _: copy.deepcopy(next(snapshots))
        with self.assertRaisesRegex(RuntimeError, "story changed"):
            s._run_write_shots({"project": "scratch", "mode": "board"}, lambda _: None)
        self.assertFalse(saved)

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

    def test_shadow_puppet_direction_reaches_cast_world_frame_and_motion(self):
        d = studio.director
        look = 'Shadow puppet animation with high-contrast blue silhouettes on parchment'
        self.assertEqual(d.medium(look), 'shadow_puppet')
        portrait = d.cast_prompt('A fisher', 'A coast', look)
        self.assertTrue(portrait.startswith('A flat silhouette shadow-puppet cutout'))
        self.assertIn('A fisher', portrait)
        self.assertIn('silhouette shapes only', portrait)
        translucent = d.cast_prompt('A fisher', 'A coast', 'Translucent blue shadow puppet animation')
        self.assertIn('Translucent blue shadow puppet animation', translucent)
        self.assertNotIn('solid dark', translucent)
        self.assertNotIn('opaque silhouette', translucent)
        self.assertIn('backlit screen', d.world_plate_prompt('A coast', look))
        self.assertIn('flat articulated silhouettes', d.shot_prompt('Raise a hand', 'Medium', look, storyboard=True))
        self.assertIn('Flat shadow-puppet silhouettes articulate', d.motion_prompt('Raise a hand', 'Static', look=look))
        self.assertIn('shadow-puppet animation', d.following_frame_prompt('Raise a hand', 'Medium', 'Lead', {}, look=look).lower())
        self.assertIn('photorealistic human face', d.image_negative(look))
        self.assertNotEqual(d.medium('Live-action photographic shadow puppets'), 'shadow_puppet')
        self.assertNotEqual(d.medium('Animation without shadow puppets'), 'shadow_puppet')

    def test_cast_anchor_review_is_advisory_and_does_not_attach_to_newer_reference(self):
        worker, saved, _ = harness([{'answer': 'NO'}])
        project = worker.load('scratch')
        project.update(reference='ref.png', look='Anime')
        worker.load = lambda _: copy.deepcopy(project)
        worker._upload = lambda *_: 'uploaded.png'
        worker._check_visual_anchor('scratch', 'ref.png', 'Anime', lambda _: None)
        self.assertEqual(saved[-1]['visual_anchor_review']['status'], 'possible_mismatch')
        self.assertIn('UNCERTAIN', worker.comfy.submitted[0]['3']['inputs']['prompt'])

        worker, saved, _ = harness([{'answer': 'YES'}])
        project['reference'] = 'new-ref.png'
        worker.load = lambda _: copy.deepcopy(project)
        worker._upload = lambda *_: 'uploaded.png'
        worker._check_visual_anchor('scratch', 'ref.png', 'Anime', lambda _: None)
        self.assertFalse(saved)

    def test_cast_anchor_reviewer_failure_is_uncertain_and_interrupt_propagates(self):
        worker, saved, _ = harness([])
        project = worker.load('scratch')
        project.update(reference='ref.png', look='Anime')
        worker.load = lambda _: copy.deepcopy(project)
        worker._upload = lambda *_: 'uploaded.png'
        worker.comfy.submit = lambda _: (_ for _ in ()).throw(RuntimeError('offline'))
        worker._check_visual_anchor('scratch', 'ref.png', 'Anime', lambda _: None)
        self.assertEqual(saved[-1]['visual_anchor_review']['status'], 'uncertain')
        worker.comfy.submit = lambda _: (_ for _ in ()).throw(studio.ComfyError('execution interrupted'))
        with self.assertRaisesRegex(studio.ComfyError, 'interrupted'):
            worker._check_visual_anchor('scratch', 'ref.png', 'Anime', lambda _: None)

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
