import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import studio
from test_asset_dependencies import fixture
import test_generation_modes


class CharacterReferenceTests(unittest.TestCase):
    def test_storyboard_uses_portrait_description_and_tracks_only_new_drawings(self):
        project, shot = fixture()
        project['review_policy'] = 'draft'
        self.assertFalse(studio.sketch_stale(project, shot))  # legacy drawing has no portrait dependency
        worker = object.__new__(studio.Studio)
        worker.lock = __import__('threading').RLock()
        worker.load = Mock(return_value=project)
        worker.save = Mock()
        worker._require_plan = Mock(return_value=project)
        worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, studio.director.review_result([])))
        worker.comfy = Mock()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            worker.path = lambda _: Path(folder)
            worker._draw_sketch(project['id'], shot['id'], lambda _: None)
        graph = worker._render_checked.call_args.args[0]
        self.assertIn('Portrait appearance: Round face and brown eyes', graph['4']['inputs']['text'])
        self.assertFalse(studio.sketch_stale(project, shot))
        project['lead_identity'] = 'A different face and hair'
        self.assertTrue(studio.sketch_stale(project, shot))
        shot['sketch'] = 'board.png'
        self.assertFalse(studio.sketch_stale(project, shot))

    def test_storyboard_keeps_but_does_not_select_result_after_portrait_changes(self):
        project, shot = fixture()
        project['review_policy'] = 'draft'
        worker = object.__new__(studio.Studio)
        worker.lock = __import__('threading').RLock()
        worker.load = Mock(return_value=project)
        worker.save = Mock()
        worker._require_plan = Mock(return_value=project)
        def render(*args, **kwargs):
            project['lead_identity'] = 'A newer description'
            return [{'filename':'made.png'}], 9, studio.director.review_result([])
        worker._render_checked = Mock(side_effect=render)
        worker.comfy = Mock()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            worker.path = lambda _: Path(folder)
            with self.assertRaisesRegex(RuntimeError, 'changed while drawing'):
                worker._draw_sketch(project['id'], shot['id'], lambda _: None)
        self.assertEqual(shot['sketch'], 'board.png')
        self.assertEqual(len(shot['sketches']), 2)

    def test_linked_reentry_uses_only_a_known_missing_individual_and_tracks_reference(self):
        project, first = fixture()
        project['review_policy'] = 'draft'
        project['character_references'] = {'Tavi': {'image':'tavi.png', 'source':'upload'}}
        first.update(start_cast=['Lead', 'Tavi'], end_cast=['Lead'], video='previous.mp4')
        second = copy.deepcopy(first)
        second.update(id='second', frame_source='previous_end', start_cast=['Lead'], end_cast=['Lead', 'Tavi'],
                      cast_roster_unresolved=['Tavi'])
        project['shots'].append(second)
        self.assertEqual(studio.selected_character_references(project, second), [{'name':'Tavi', 'image':'tavi.png'}])
        before = studio.visual_inputs(project, second)
        project['character_references']['Tavi']['image'] = 'new.png'
        self.assertNotEqual(before, studio.visual_inputs(project, second))
        self.assertNotIn('character_references', studio.sketch_visual_inputs(project, second))
        first['end_cast'] = None
        self.assertEqual(studio.selected_character_references(project, second), [])
        first['end_cast'] = ['Lead', 'Tavi']
        self.assertEqual(studio.selected_character_references(project, second), [])
        first['end_cast'] = ['Lead']
        second['cast_roster_unresolved'] = []
        self.assertEqual(studio.selected_character_references(project, second), [])
        second['start_cast'].append('Tavi')
        self.assertEqual(studio.selected_character_references(project, second)[0]['name'], 'Tavi')
        second['start_frame'] = 'Lead waits while Tavi is offscreen'
        self.assertEqual(studio.selected_character_references(project, second), [])
        second['start_frame'] = 'Lead waits without Tavi'
        self.assertEqual(studio.selected_character_references(project, second), [])
        second['start_frame'] = 'Lead faces Tavi'
        project['frame_backend'] = 'klein'
        self.assertEqual(studio.selected_character_references(project, second), [])

    def test_linked_frame_supplies_returning_identity_as_second_picture(self):
        project, first = fixture()
        project['review_policy'] = 'draft'
        project['character_references'] = {'Tavi': {'image':'tavi.png', 'source':'upload'}}
        first.update(end_cast=['Lead'], video='previous.mp4')
        second = copy.deepcopy(first)
        second.update(id='second', frame_source='previous_end', start_cast=['Lead'], end_cast=['Lead', 'Tavi'],
                      cast_roster_unresolved=['Tavi'], start_frame='Lead waits as Tavi enters')
        project['shots'].append(second)
        worker = object.__new__(studio.Studio)
        worker.lock = __import__('threading').RLock()
        worker.load = Mock(return_value=project)
        worker._require_plan = Mock(return_value=project)
        worker._upload = lambda _, name: 'uploaded_' + name
        worker._current_sketch = Mock(return_value='board.png')
        worker._last_frame = Mock(return_value='previous-end.png')
        worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, {}))
        worker._finish_keyframe = Mock()
        worker.comfy = Mock()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            worker.path = lambda _: Path(folder)
            with patch.object(studio, 'video_stale', return_value=False), patch.object(studio, 'take_usable', return_value=True):
                worker._run_keyframe({'project':'scratch', 'shot':'second', 'frame_backend':'qwen'}, lambda _: None)
        graph = worker._render_checked.call_args.args[0]
        self.assertEqual(graph['16']['inputs']['image'], 'uploaded_tavi.png')
        self.assertIn('Picture 2 is an identity reference for Tavi', graph['8']['inputs']['prompt'])
        self.assertIn('follow the staging for when they appear', graph['8']['inputs']['prompt'])
        self.assertEqual(worker._finish_keyframe.call_args.args[5]['character_references'], [{'name':'Tavi', 'image':'tavi.png'}])

    def test_legacy_mixed_style_portraits_remain_current_but_edits_stale_them(self):
        project, _ = fixture()
        project.update(cast='Rae, an adult human', look='Live-action photography of a stop-motion set')
        project['reference_prompt'] = studio.director.legacy_mixed_cast_prompt(project['cast'], project['look'])
        project['characters'] = 'Pip: a cloth puppet'
        project['character_references'] = {'Pip': {'source':'generated', 'image':'pip.png',
            'prompt':studio.director.legacy_mixed_cast_prompt('Pip, a cloth puppet', project['look'])}}
        self.assertFalse(studio.cast_stale(project))
        self.assertIsNotNone(studio.current_character_reference(project, 'Pip'))
        project['cast'] = 'Rae, an adult human with glasses'
        project['characters'] = 'Pip: a cloth puppet with a scarf'
        self.assertTrue(studio.cast_stale(project))
        self.assertIsNone(studio.current_character_reference(project, 'Pip'))
    def test_character_reentering_after_opening_is_recurring(self):
        project, first = fixture()
        first.update(start_cast=['Lead', 'Tavi'], end_cast=['Lead'])
        second = copy.deepcopy(first)
        second.update(id='second', start_cast=['Lead'], end_cast=['Lead', 'Tavi'])
        project['shots'].append(second)
        self.assertEqual(studio.recurring_character_names(project), ['Tavi'])

    def test_guided_ending_uses_returning_portrait_and_tracks_changes(self):
        import threading
        project, shot = fixture()
        project['review_policy'] = 'draft'
        project['character_references'] = {'Tavi': {'image': 'tavi.png', 'source': 'upload'}}
        shot.update(start_cast=['Lead'], end_cast=['Lead', 'Tavi'], guide_end=True, endframe=None)
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.load = Mock(return_value=project)
        worker.save = Mock()
        worker._upload = lambda _, name: 'uploaded_' + name
        worker.comfy = Mock()
        worker.comfy.run.return_value = [{'filename':'made.png'}]
        review = studio.director.review_result([])
        worker._review_image = Mock(return_value=review)
        worker._repair_frame = Mock(side_effect=lambda p, s, name, r, *a: (name, r))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            worker.path = lambda _: Path(folder)
            name = worker._ending_frame(project, shot, 'frame.png', lambda _: None)
        graph = worker.comfy.run.call_args.args[0]
        worker._repair_frame.assert_not_called()
        self.assertEqual(graph['16']['inputs']['image'], 'uploaded_tavi.png')
        self.assertIn('Picture 2 is Tavi', graph['8']['inputs']['prompt'])
        self.assertEqual(shot['endframe']['name'], name)
        before = studio.video_inputs(project, shot)
        self.assertEqual(before['end_character_references'], [{'name':'Tavi', 'image':'tavi.png'}])
        project['character_references']['Tavi']['image'] = 'replacement.png'
        self.assertNotEqual(before, studio.video_inputs(project, shot))
        self.assertNotEqual(shot['endframe']['of'], studio.ending_inputs(project, shot))

    def test_strict_guided_ending_keeps_repair_workflow(self):
        import threading
        project, shot = fixture()
        project['review_policy'] = 'strict'
        shot.update(start_cast=['Lead'], end_cast=['Lead', 'Tavi'], guide_end=True, endframe=None)
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.load = Mock(return_value=project)
        worker.save = Mock()
        worker._upload = lambda _, name: name
        worker.comfy = Mock()
        worker.comfy.run.return_value = [{'filename':'made.png'}]
        review = studio.director.review_result([])
        worker._review_image = Mock(return_value=review)
        worker._repair_frame = Mock(side_effect=lambda p, s, name, r, *a: (name, r))
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            worker.path = lambda _: Path(folder)
            worker._ending_frame(project, shot, 'frame.png', lambda _: None)
        worker._repair_frame.assert_called_once()

    def test_guided_ending_keeps_newer_edit_and_retains_candidate(self):
        import threading
        project, shot = fixture()
        project['review_policy'] = 'draft'
        shot.update(guide_end=True, endframe=None)
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.load = Mock(return_value=project)
        worker.save = Mock()
        worker._upload = lambda _, name: name
        worker.comfy = Mock()
        worker.comfy.run.return_value = [{'filename':'made.png'}]
        def review(*args):
            shot['end_state'] = 'A newer ending'
            return studio.director.review_result([])
        worker._review_image = review
        worker._repair_frame = Mock()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            worker.path = lambda _: Path(folder)
            with self.assertRaisesRegex(RuntimeError, 'changed while rendering'):
                worker._ending_frame(copy.deepcopy(project), copy.deepcopy(shot), 'frame.png', lambda _: None)
        self.assertIsNone(shot['endframe'])
        self.assertEqual(len(shot['endframes']), 1)
        worker._repair_frame.assert_not_called()

    def test_uploaded_end_frame_does_not_depend_on_portrait(self):
        import threading
        project, shot = fixture()
        project['review_policy'] = 'draft'
        project['character_references'] = {'Tavi': {'image': 'tavi.png', 'source': 'upload'}}
        shot.update(start_cast=['Lead'], end_cast=['Lead', 'Tavi'], guide_end=True)
        snapshot = studio.ending_inputs(project, shot)
        snapshot.pop('end_character_references')
        shot['endframe'] = {'name':'uploaded.png', 'source':'upload', 'of':snapshot,
                            'review':{'version':studio.director.REVIEW_VERSION, 'status':'needs_review'}}
        before = studio.video_inputs(project, shot)
        project['character_references']['Tavi']['image'] = 'new.png'
        self.assertEqual(before, studio.video_inputs(project, shot))
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.comfy = Mock()
        self.assertEqual(worker._ending_frame(project, shot, 'frame.png', lambda _: None), 'uploaded.png')
        worker.comfy.run.assert_not_called()

    def test_reentering_character_reference_is_queued_for_first_shot(self):
        worker, project, shot = test_generation_modes.GenerationModesTests().fake()
        project['review_policy'] = 'draft'
        first, second = project['shots'][:2]
        first.update(start_cast=['Lead', 'Tavi'], end_cast=['Lead'], sketch=None, keyframe=None, video=None,
                     sketches=[], takes={'keyframe': [], 'video': []})
        second.update(start_cast=['Lead'], end_cast=['Lead', 'Tavi'], sketch=None, keyframe=None, video=None,
                      sketches=[], takes={'keyframe': [], 'video': []})
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        worker._save_jobs = lambda: None
        worker.queue_film(project['id'])
        jobs = [worker.queue.get()[2] for _ in range(worker.queue.qsize())]
        self.assertTrue(any(job['kind'] == 'character_reference' and job['character'] == 'Tavi' for job in jobs))

    def test_only_recurring_individuals_are_automatically_cast(self):
        project, shot = fixture()
        other = copy.deepcopy(shot)
        other.update(id='second', start_cast=['Lead', 'Tavi', 'Crowd'])
        shot['start_cast'] = ['Lead', 'Tavi', 'Crowd']
        project['characters'] += '\nCrowd: a group of villagers'
        project['shots'].append(other)
        self.assertEqual(studio.recurring_character_names(project), ['Tavi'])

    def test_recurring_portrait_is_queued_before_first_frame_and_never_replaces_upload(self):
        for uploaded in (False, True):
            worker, project, shot = test_generation_modes.GenerationModesTests().fake()
            project['review_policy'] = 'draft'
            for item in project['shots']:
                item.update(sketch=None, keyframe=None, video=None, start_cast=['Lead', 'Tavi'],
                            sketches=[], takes={'keyframe':[], 'video':[]})
            if uploaded:
                project['character_references'] = {'Tavi':{'image':'manual.png', 'source':'upload'}}
            project['continuity_plan']['of'] = studio.continuity_inputs(project)
            worker._save_jobs = lambda: None
            worker.queue_film(project['id'])
            jobs = [worker.queue.get()[2] for _ in range(worker.queue.qsize())]
            references = [job for job in jobs if job['kind'] == 'character_reference']
            if uploaded:
                self.assertEqual(references, [])
            else:
                self.assertEqual(len(references), 1)
                self.assertEqual(references[0]['character'], 'Tavi')
                self.assertLess(jobs.index(references[0]), next(i for i, job in enumerate(jobs)
                                      if job['kind'] == 'keyframe' and job['shot'] == shot['id']))

    def test_distinct_named_portraits_are_not_deduplicated_together(self):
        worker, project, _ = test_generation_modes.GenerationModesTests().fake()
        project['characters'] = 'Tavi: green coat\nMara: red scarf'
        worker._save_jobs = lambda: None
        first = worker.queue_character_reference(project['id'], 'Tavi')
        second = worker.queue_character_reference(project['id'], 'Mara')
        repeat = worker.queue_character_reference(project['id'], 'Tavi')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(first['id'], repeat['id'])

    def test_portraits_are_used_only_when_visible_and_within_slot_budget(self):
        project, shot = fixture()
        project['character_references'] = {'Tavi': {'image': 'tavi.png', 'source': 'upload'}}
        shot['start_cast'] = ['Lead', 'Tavi']
        self.assertEqual(studio.selected_character_references(project, shot), [{'name':'Tavi', 'image':'tavi.png'}])
        self.assertIn('character_references', studio.visual_inputs(project, shot))
        shot['start_cast'] = ['Lead']
        self.assertEqual(studio.selected_character_references(project, shot), [])
        shot['start_cast'] = ['Lead', 'Tavi']
        shot['frame_source'] = 'previous_end'
        self.assertEqual(studio.selected_character_references(project, shot), [])
        shot['frame_source'] = 'storyboard'
        project['props'] = [{'id':'cup','name':'Cup','description':'blue cup','state_key':'cup'}]
        project['scene_state'] = {'cup':'whole'}
        shot['prop_id'] = 'cup'
        self.assertEqual(studio.selected_character_references(project, shot), [])

    def test_available_later_portrait_fills_slot_when_first_is_missing(self):
        project, shot = fixture()
        project['characters'] += '\nMara: red scarf'
        shot['start_cast'] = ['Lead', 'Tavi', 'Mara']
        project['character_references'] = {'Mara': {'image':'mara.png', 'source':'upload'}}
        self.assertEqual(studio.selected_character_references(project, shot), [{'name':'Mara', 'image':'mara.png'}])

    def test_strict_never_uses_failed_generated_portrait_or_discards_upload(self):
        project, shot = fixture()
        project['review_policy'] = 'strict'
        prompt = studio.director.cast_prompt('Tavi, curly hair, green coat', project['scene'], project['look'])
        project['character_references'] = {'Tavi': {'image':'failed.png', 'source':'generated', 'prompt':prompt,
                                                    'review':{'status':'needs_review','outcome':'content_issue'}}}
        self.assertEqual(studio.selected_character_references(project, shot), [])
        project['character_references']['Tavi'].update(image='manual.png', source='upload')
        self.assertEqual(studio.selected_character_references(project, shot), [{'name':'Tavi','image':'manual.png'}])

    def test_stale_generated_reference_is_ignored_but_upload_is_preserved(self):
        project, _ = fixture()
        prompt = studio.director.cast_prompt('Tavi, curly hair, green coat', project['scene'], project['look'])
        project['character_references'] = {'Tavi': {'image':'tavi.png', 'source':'generated', 'prompt':prompt}}
        self.assertIsNotNone(studio.current_character_reference(project, 'tavi'))
        project['characters'] = 'Tavi: curly hair, red coat'
        self.assertIsNone(studio.current_character_reference(project, 'Tavi'))
        project['character_references']['Tavi']['source'] = 'upload'
        self.assertIsNotNone(studio.current_character_reference(project, 'Tavi'))

    def test_new_reference_preserves_legacy_takes_and_tracks_frames_that_use_it(self):
        project, shot = fixture()
        before = studio.sketch_of(shot, None, None, project)
        project['character_references'] = {'Tavi': {'image':'tavi.png', 'source':'upload'}}
        self.assertEqual(before, studio.sketch_of(shot, None, None, project))
        self.assertFalse(studio.frame_stale(project, shot))
        self.assertFalse(studio.video_stale(project, shot))
        shot['takes']['keyframe'][0]['recipe']['visual'] = studio.visual_inputs(project, shot)
        project['character_references']['Tavi']['image'] = 'new-tavi.png'
        self.assertTrue(studio.frame_stale(project, shot))

    def test_selected_frame_editor_receives_named_reference_and_lead(self):
        project, shot = fixture()
        project['character_references'] = {'Tavi': {'image':'tavi.png', 'source':'upload'}}
        worker = object.__new__(studio.Studio)
        worker.lock = __import__('threading').RLock()
        worker.load = Mock(return_value=project)
        worker._require_plan = Mock(return_value=project)
        worker._upload = lambda _, name: 'uploaded_' + name
        worker._current_sketch = Mock(return_value='board.png')
        worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, {}))
        worker._finish_keyframe = Mock()
        worker.comfy = Mock()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            worker.path = lambda _: Path(folder)
            worker._run_keyframe({'project':'scratch','shot':shot['id'],'frame_backend':'klein'}, lambda _: None)
        graph = worker._render_checked.call_args.args[0]
        self.assertEqual(graph['ref1']['inputs']['image'], 'uploaded_board.png')
        self.assertEqual(graph['ref2']['inputs']['image'], 'uploaded_portrait.png')
        self.assertEqual(graph['ref3']['inputs']['image'], 'uploaded_tavi.png')
        self.assertIn('Picture 3 is the character Tavi', graph['4']['inputs']['text'])
        recipe = worker._finish_keyframe.call_args.args[5]
        self.assertEqual(recipe['frame_backend'], 'klein')
        self.assertFalse(recipe['world_reference'])

    def test_explicit_mixed_cast_uses_identity_images_without_stylized_board(self):
        for backend in ('qwen', 'klein'):
            project, shot = fixture()
            project.update(look='Live-action photography', cast='Rae, an adult human in blue',
                           characters='Tavi: a cloth puppet with green coat')
            project['character_references'] = {'Tavi': {'image':'tavi.png', 'source':'upload'}}
            shot.update(start_cast=['Rae','Tavi'])
            worker = object.__new__(studio.Studio)
            worker.lock = __import__('threading').RLock()
            worker.load = Mock(return_value=project)
            worker._require_plan = Mock(return_value=project)
            worker._upload = lambda _, name: 'uploaded_' + name
            worker._current_sketch = Mock(return_value='board.png')
            worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, {}))
            worker._finish_keyframe = Mock()
            worker.comfy = Mock()
            with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
                worker.path = lambda _: Path(folder)
                with patch.object(studio, 'cast_stale', return_value=False), patch.object(studio, 'story_stale', return_value=False), \
                     patch.object(studio, 'current_plate', return_value='world.png'):
                    worker._run_keyframe({'project':'scratch','shot':shot['id'],'frame_backend':backend}, lambda _: None)
            graph = worker._render_checked.call_args.args[0]
            self.assertEqual(graph['ref1' if backend == 'klein' else '6']['inputs']['image'], 'uploaded_portrait.png')
            self.assertEqual(graph['ref2' if backend == 'klein' else '16']['inputs']['image'], 'uploaded_tavi.png')
            self.assertNotIn('uploaded_board.png', str(graph))
            recipe = worker._finish_keyframe.call_args.args[5]
            self.assertEqual(recipe['composition_source'], 'cast_portraits')
            self.assertEqual(recipe['source_frame'], 'portrait.png')

    def test_portrait_composition_does_not_depend_on_unused_board_or_world_images(self):
        project, shot = fixture()
        recipe = studio.current_take(shot, 'keyframe')['recipe']
        recipe['composition_source'] = 'cast_portraits'
        shot['sketch'] = 'another-board.png'
        project['world']['plate'] = 'another-world.png'
        self.assertFalse(studio.frame_stale(project, shot))
        project['reference'] = 'another-face.png'
        self.assertTrue(studio.frame_stale(project, shot))

    def test_no_lead_wide_shot_assigns_distinct_picture_numbers_to_cast_and_world(self):
        for backend in ('qwen', 'klein'):
            with self.subTest(backend=backend):
                project, shot = fixture()
                shot.update(lead=False, start_cast=['Tavi'], shot_size='Wide')
                project['character_references'] = {'Tavi': {'image':'tavi.png', 'source':'upload'}}
                worker = object.__new__(studio.Studio)
                worker.lock = __import__('threading').RLock()
                worker.load = Mock(return_value=project)
                worker._require_plan = Mock(return_value=project)
                worker._upload = lambda _, name: 'uploaded_' + name
                worker._current_sketch = Mock(return_value='board.png')
                worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, {}))
                worker._finish_keyframe = Mock()
                worker.comfy = Mock()
                with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
                    worker.path = lambda _: Path(folder)
                    worker._run_keyframe({'project':'scratch','shot':shot['id'],'frame_backend':backend}, lambda _: None)
                graph = worker._render_checked.call_args.args[0]
                prompt = graph['4']['inputs']['text'] if backend == 'klein' else graph['8']['inputs']['prompt']
                self.assertIn('Picture 2 is the character Tavi', prompt)
                self.assertIn('Location context from Picture 3', prompt)
                if backend == 'klein':
                    self.assertEqual(graph['ref2']['inputs']['image'], 'uploaded_tavi.png')
                    self.assertEqual(graph['ref3']['inputs']['image'], 'uploaded_world.png')
                else:
                    self.assertEqual(graph['16']['inputs']['image'], 'uploaded_tavi.png')
                    self.assertEqual(graph['18']['inputs']['image'], 'uploaded_world.png')

    def test_tight_frames_receive_full_setting_without_a_world_picture(self):
        for backend in ('qwen', 'klein'):
            with self.subTest(backend=backend):
                project, shot = fixture()
                project['scene'] = 'A stop-motion puppet workshop. Copper machinery stands beneath a cracked glass ceiling.'
                project['world']['takes'][0]['of'] = studio.world_of(project)
                shot.update(shot_size='Medium', start_frame='The puppet examines a parcel at a table')
                worker = object.__new__(studio.Studio)
                worker.lock = __import__('threading').RLock()
                worker.load = Mock(return_value=project)
                worker._require_plan = Mock(return_value=project)
                worker._upload = lambda _, name: 'uploaded_' + name
                worker._current_sketch = Mock(return_value='board.png')
                worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, {}))
                worker._finish_keyframe = Mock()
                worker.comfy = Mock()
                with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
                    worker.path = lambda _: Path(folder)
                    worker._run_keyframe({'project':'scratch','shot':shot['id'],'frame_backend':backend}, lambda _: None)
                graph = worker._render_checked.call_args.args[0]
                prompt = graph['4']['inputs']['text'] if backend == 'klein' else graph['8']['inputs']['prompt']
                self.assertIn('Location context: A stop-motion puppet workshop. Copper machinery stands beneath a cracked glass ceiling.', prompt)
                self.assertIn('Keep the storyboard\'s camera view, crop and subject placement', prompt)
                self.assertIn('complete a plain or incomplete background using the location context', prompt)
                self.assertNotIn('Location context from Picture', prompt)
                self.assertFalse(worker._finish_keyframe.call_args.args[5]['world_reference'])

    def test_tight_frames_with_supporting_portrait_do_not_mislabel_it_as_world(self):
        for backend in ('qwen', 'klein'):
            with self.subTest(backend=backend):
                project, shot = fixture()
                project['scene'] = 'A brick workshop. Moonlight falls through its tall windows.'
                project['world']['takes'][0]['of'] = studio.world_of(project)
                project['character_references'] = {'Tavi': {'image':'tavi.png', 'source':'upload'}}
                shot['shot_size'] = 'Medium'
                worker = object.__new__(studio.Studio)
                worker.lock = __import__('threading').RLock()
                worker.load = Mock(return_value=project)
                worker._require_plan = Mock(return_value=project)
                worker._upload = lambda _, name: 'uploaded_' + name
                worker._current_sketch = Mock(return_value='board.png')
                worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, {}))
                worker._finish_keyframe = Mock()
                worker.comfy = Mock()
                with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
                    worker.path = lambda _: Path(folder)
                    worker._run_keyframe({'project':'scratch','shot':shot['id'],'frame_backend':backend}, lambda _: None)
                graph = worker._render_checked.call_args.args[0]
                prompt = graph['4']['inputs']['text'] if backend == 'klein' else graph['8']['inputs']['prompt']
                self.assertIn('Picture 3 is the character Tavi', prompt)
                self.assertIn('Location context: A brick workshop. Moonlight falls through its tall windows.', prompt)
                self.assertNotIn('Location context from Picture 3', prompt)

    def test_no_lead_wide_shot_assigns_distinct_picture_numbers_to_prop_and_world(self):
        project, shot = fixture()
        shot.update(lead=False, start_cast=[], shot_size='Wide', prop_id='cup')
        prop = {'id':'cup','name':'Cup','description':'blue cup','state_key':'cup'}
        prop['variants'] = {'whole': {'name':'cup.png','of':studio.prop_design(project, prop)}}
        project['props'], project['scene_state'] = [prop], {'cup':'whole'}
        worker = object.__new__(studio.Studio)
        worker.lock = __import__('threading').RLock()
        worker.load = Mock(return_value=project)
        worker._require_plan = Mock(return_value=project)
        worker._upload = lambda _, name: 'uploaded_' + name
        worker._current_sketch = Mock(return_value='board.png')
        worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, {}))
        worker._finish_keyframe = Mock()
        worker.comfy = Mock()
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            worker.path = lambda _: Path(folder)
            worker._run_keyframe({'project':'scratch','shot':shot['id']}, lambda _: None)
        graph = worker._render_checked.call_args.args[0]
        self.assertEqual(graph['16']['inputs']['image'], 'uploaded_cup.png')
        self.assertEqual(graph['18']['inputs']['image'], 'uploaded_world.png')
        self.assertIn('Location context from Picture 3', graph['8']['inputs']['prompt'])

    def test_manual_upload_wins_if_generation_completes_after_it(self):
        project, _ = fixture()
        worker = object.__new__(studio.Studio)
        worker.lock = __import__('threading').RLock()
        newer = copy.deepcopy(project)
        newer['character_references'] = {'Tavi': {'image':'manual.png', 'source':'upload'}}
        snapshots = iter([copy.deepcopy(project), newer])
        worker.load = lambda _: next(snapshots)
        worker.save = Mock()
        worker.comfy = Mock()
        worker.comfy.run.return_value = [{'filename':'generated.png'}]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
            worker.path = lambda _: Path(folder)
            with self.assertRaisesRegex(RuntimeError, 'newer edit was kept'):
                worker._run_character_reference({'project':'scratch','character':'Tavi'}, lambda _: None)
        worker.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
