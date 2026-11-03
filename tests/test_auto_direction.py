import copy
import json
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

import test_generation_modes
import test_story_pipeline
import studio


class AutoDirectionTests(unittest.TestCase):
    def test_directed_angle_round_trips_without_changing_existing_cut_format(self):
        base = ('SHOT: 1 | The lead hands over the cup | Medium | Static | 4 | room tone | '
                'lead, Tavi | - | {} | Cup in lead hand | Cup in Tavi hand')
        reframe = studio.director.parse_shots(base.format('reframe'))[0]
        self.assertEqual((reframe['transition'], reframe['frame_source']), ('cut', 'previous_end'))
        self.assertEqual(studio.director.parse_shots('SHOT: ' + studio.director.shot_line(reframe))[0]['frame_source'],
                         'previous_end')
        continuous = studio.director.parse_shots(base.format('continue'))[0]
        self.assertEqual((continuous['transition'], continuous['frame_source']), ('continue', 'storyboard'))
        cut = studio.director.parse_shots(base.format('cut'))[0]
        self.assertEqual((cut['transition'], cut['frame_source']), ('cut', 'storyboard'))

    def test_director_has_story_based_choices_not_mandatory_reframes(self):
        brief = studio.director.shot_brief('board', logline='Two friends share a table')
        self.assertIn('cut, reframe, or continue', brief)
        self.assertIn('Choose only when the story supports it', brief)
        self.assertIn('first shot of the film, with no preceding shot, must be cut', brief)
        self.assertIn('specify the actual new camera viewpoint in the start frame', brief)
        self.assertIn('whose face is visible', brief)
        self.assertIn('whose back or shoulder is in the foreground', brief)
        self.assertIn('which named people are outside the frame', brief)
        self.assertIn('Include only people actually visible in who', brief)
        self.assertIn('do not invent an angle, person, or exclusion contrary to the story', brief)
        self.assertIn('a reaction shot may leave other people offscreen', brief)

    def test_script_supervisor_preserves_single_subject_reaction_and_foreground_identity(self):
        review = studio.director.shot_review_brief('story', 'draft')
        self.assertIn('other people may remain offscreen', review)
        self.assertIn('including anyone partly visible in the foreground', review)
        self.assertIn('A foreground person is the same individual, not another copy', review)
        self.assertIn('rather than inventing extra events, people or exclusions', review)
        self.assertNotIn('Every person required for an exchange must be visible', review)

    def test_reframe_preserves_the_written_viewpoint_without_inventing_people(self):
        staging = 'From behind the elder, their head in the foreground; the courier faces camera'
        prompt = studio.director.following_frame_prompt(staging, 'Close-up', 'Elder; courier', {}, expected_count=2)
        self.assertIn(staging, prompt)
        self.assertIn('Exactly 2 visible characters', prompt)
        self.assertNotIn('No characters are visible', prompt)

    def test_linked_cast_retains_visible_descriptions_and_current_lead_identity(self):
        from test_asset_dependencies import fixture
        project, first = fixture()
        project['cast'] = 'Mira, short black hair, yellow jacket'
        project['characters'] = 'Noah: curly hair, blue jacket and round glasses\nOffscreen: red hat'
        project['lead_identity'] = 'Round face and brown eyes'
        first['end_cast'] = ['Mira', 'Noah']
        shot = copy.deepcopy(first)
        shot.update(id='second', start_cast=[' Lead ', ' Noah '], lead=True, others='Noah')
        project['shots'].append(shot)
        result = studio.linked_cast_direction(project, shot, first)
        self.assertIn('Mira, the same person already in Picture 1', result)
        self.assertIn('yellow jacket', result)
        self.assertIn('Round face and brown eyes', result)
        self.assertIn('Noah, the same person already in Picture 1, curly hair, blue jacket and round glasses', result)
        self.assertNotIn('Offscreen', result)
        project['lead_identity_of'] = 'old-portrait.png'
        self.assertNotIn('Round face and brown eyes', studio.linked_cast_direction(project, shot, first))

    def test_linked_cast_legacy_roster_and_groups_do_not_invent_individuals(self):
        from test_asset_dependencies import fixture
        project, first = fixture()
        project['cast'] = 'Mira, black hair'
        project['characters'] = 'Noah: round glasses\nOffscreen: red hat'
        first['end_cast'] = ['Noah', 'Crowd']
        legacy = copy.deepcopy(first)
        legacy.update(id='second', lead=False, others='Noah', action='Noah waits')
        legacy.pop('start_cast', None)
        project['shots'].append(legacy)
        result = studio.linked_cast_direction(project, legacy, first)
        self.assertIn('Noah, the same person already in Picture 1, round glasses', result)
        self.assertNotIn('Mira', result)
        self.assertNotIn('Offscreen', result)
        crowd = {**legacy, 'start_cast': ['Crowd'], 'lead': False, 'others': 'Crowd'}
        result = studio.linked_cast_direction(project, crowd, first)
        self.assertIn('Crowd, the same group already in Picture 1', result)
        self.assertNotIn('same person', result)
        self.assertNotIn('Noah', result)

    def test_previous_end_reframe_passes_explicit_viewpoint_to_frame_and_motion(self):
        from test_asset_dependencies import fixture
        project, first = fixture()
        second = copy.deepcopy(first)
        staging = "Over Tavi's shoulder, looking toward the lead holding the cup"
        second.update(id='second', frame_source='previous_end', start_frame=staging,
                      shot_size='Over the shoulder', camera_move='Crane up', keyframe=None, video=None,
                      start_cast=['Lead', 'Tavi'], takes={'keyframe': [], 'video': []})
        project['shots'].append(second)
        for backend in ('qwen', 'klein'):
            with self.subTest(backend=backend):
                worker = object.__new__(studio.Studio)
                worker.lock = threading.RLock()
                worker.load = Mock(return_value=project)
                worker._require_plan = Mock(return_value=project)
                worker._current_sketch = Mock(return_value='board.png')
                worker._last_frame = Mock(return_value='previous.png')
                worker._upload = lambda _, name: 'uploaded_' + name
                worker._render_checked = Mock(return_value=([{'filename': 'made.png'}], 9, {}))
                worker._finish_keyframe = Mock()
                worker.comfy = Mock()
                with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
                    worker.path = lambda _: Path(folder)
                    with patch.object(studio, 'cast_stale', return_value=False), \
                         patch.object(studio, 'story_stale', return_value=False), \
                         patch.object(studio, 'video_stale', return_value=False), \
                         patch.object(studio, 'take_usable', return_value=True):
                        worker._run_keyframe({'project': 'scratch', 'shot': 'second', 'frame_backend': backend}, lambda _: None)
                graph = worker._render_checked.call_args.args[0]
                prompt = graph['4']['inputs']['text'] if backend == 'klein' else graph['8']['inputs']['prompt']
                self.assertIn(staging, prompt)
                self.assertIn('over-the-shoulder shot', prompt)
                self.assertIn('low camera close to the ground', prompt)
                self.assertIn('rather than merely cropping Picture 1', prompt)
                self.assertIn('Exactly 2 visible characters', prompt)
                self.assertIn('show each individual only once', prompt)
                self.assertEqual(graph['ref1' if backend == 'klein' else '6']['inputs']['image'], 'uploaded_previous.png')
                self.assertNotIn('ref2' if backend == 'klein' else '16', graph)
                self.assertEqual(graph['checked']['inputs']['expected'], 2)
                self.assertEqual(graph['count']['inputs']['image'], ['10' if backend == 'klein' else '14', 0])
        motion = studio.director.motion_prompt(second['action'], second['camera_move'], start_frame=staging)
        self.assertIn(staging, motion)

    def test_reframe_cast_count_is_unknown_for_crowds_or_unresolved_people(self):
        from test_asset_dependencies import fixture
        for names, expected in ((None, None), (['Lead', 'Crowd'], None),
                                (['Lead', 'two workers'], 3), (['Lead', 'Unknown person'], None), ([], 0)):
            with self.subTest(names=names):
                project, first = fixture()
                second = copy.deepcopy(first)
                second.update(id='second', frame_source='previous_end', start_cast=names,
                              keyframe=None, video=None, takes={'keyframe': [], 'video': []})
                project['shots'].append(second)
                worker = object.__new__(studio.Studio)
                worker.lock = threading.RLock()
                worker.load = Mock(return_value=project)
                worker._require_plan = Mock(return_value=project)
                worker._current_sketch = Mock(return_value='board.png')
                worker._last_frame = Mock(return_value='previous.png')
                worker._upload = lambda _, name: 'uploaded_' + name
                worker._render_checked = Mock(return_value=([{'filename': 'made.png'}], 9, {}))
                worker._finish_keyframe = Mock()
                worker.comfy = Mock()
                with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'runtime') as folder:
                    worker.path = lambda _: Path(folder)
                    with patch.object(studio, 'cast_stale', return_value=False), \
                         patch.object(studio, 'story_stale', return_value=False), \
                         patch.object(studio, 'video_stale', return_value=False), \
                         patch.object(studio, 'take_usable', return_value=True), \
                         patch.object(studio.director, 'following_frame_prompt', wraps=studio.director.following_frame_prompt) as build:
                        worker._run_keyframe({'project': 'scratch', 'shot': 'second'}, lambda _: None)
                self.assertEqual(build.call_args.kwargs['expected_count'], expected)
                prompt = worker._render_checked.call_args.args[0]['8']['inputs']['prompt']
                graph = worker._render_checked.call_args.args[0]
                if expected is None:
                    self.assertNotIn('visible characters in this frame', prompt)
                    self.assertNotIn('show each individual only once', prompt)
                    self.assertNotIn('cast_review', graph)
                elif expected == 0:
                    self.assertIn('No characters are visible', prompt)
                    self.assertNotIn('cast_review', graph)
                else:
                    self.assertIn(f'Exactly {expected} visible characters', prompt)
                    self.assertEqual(graph['checked']['inputs']['expected'], expected)

    def test_pausing_a_shot_holds_dependent_reframes_and_continuations(self):
        obj, project, first = test_generation_modes.GenerationModesTests().fake()
        first['paused'] = True
        project['shots'][1]['frame_source'] = 'previous_end'
        project['shots'][2]['transition'] = 'continue'
        project['shots'][3]['video'] = None
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        obj._save_jobs = lambda: None
        obj.queue_sketches = lambda *args, **kwargs: []
        jobs = obj.queue_film('scratch')
        self.assertEqual([job['shot'] for job in jobs if job['kind'] == 'video'], ['fourth'])
        self.assertFalse(any(job['kind'] == 'stitch' for job in jobs))

    def test_pausing_a_memory_source_holds_its_return(self):
        obj, project, first = test_generation_modes.GenerationModesTests().fake()
        first['paused'] = True
        project['shots'][2]['memory_shot'] = first['id']
        project['shots'][2]['video'] = None
        project['continuity_plan']['of'] = studio.continuity_inputs(project)
        obj._save_jobs = lambda: None
        obj.queue_sketches = lambda *args, **kwargs: []
        jobs = obj.queue_film('scratch')
        self.assertNotIn('third', [job['shot'] for job in jobs if job['kind'] == 'video'])
        self.assertFalse(any(job['kind'] == 'stitch' for job in jobs))

    def test_solo_memory_rear_view_uses_description_and_not_face_portrait(self):
        for opening, backend, look, optimized in (("Over Asha's shoulder", 'qwen', 'Naturalistic live-action', True),
                                            ("Asha faces the camera", 'qwen', 'Naturalistic live-action', False),
                                            ("Over Asha's shoulder", 'klein', 'Naturalistic live-action', False),
                                            ("Over Asha's shoulder", 'qwen', 'Paper-cut animation', False)):
            with self.subTest(opening=opening, backend=backend, look=look):
                _, project, first = test_generation_modes.GenerationModesTests().fake()
                project.update(cast='Asha, short black hair, green cardigan, brown eyes', look=look,
                               lead_identity='Short black hair, oval face, brown eyes',
                               lead_identity_of='portrait.png')
                shot = project['shots'][2]
                shot.update(start_frame=opening, start_cast=['Asha'], others='', memory_shot=first['id'],
                            frame_source='storyboard', transition='cut', keyframe=None, video=None,
                            takes={'keyframe':[], 'video':[]})
                worker = object.__new__(studio.Studio)
                worker.lock = threading.RLock()
                worker.load = Mock(return_value=project)
                worker._require_plan = Mock(return_value=project)
                worker._current_sketch = Mock(return_value='board.png')
                worker._memory_plate = Mock(return_value='memory.png')
                worker._upload = lambda _, name: 'uploaded_' + name
                worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, {}))
                worker._recover_linked_cast = Mock(return_value=('made.png','prompt',9,None,False))
                worker._finish_keyframe = Mock()
                worker.comfy = Mock()
                with tempfile.TemporaryDirectory(dir='runtime') as folder:
                    worker.path = lambda _: Path(folder)
                    with patch.object(studio, 'cast_stale', return_value=False), \
                         patch.object(studio, 'story_stale', return_value=False), \
                         patch.object(studio, 'current_plate', return_value='world.png'), \
                         patch.object(studio, 'visual_memory', return_value={'shot':first['id'], 'image':'first.png', 'state':{}}):
                        worker._run_keyframe({'project':project['id'], 'shot':shot['id'], 'frame_backend':backend}, lambda _: None)
                graph = worker._render_checked.call_args.args[0]
                prompt = graph['4']['inputs']['text'] if backend == 'klein' else graph['8']['inputs']['prompt']
                recipe = worker._finish_keyframe.call_args.args[5]
                self.assertEqual(bool(recipe['lead_description_source']), optimized)
                if optimized:
                    self.assertEqual(graph['16']['inputs']['image'], 'uploaded_memory.png')
                    self.assertNotIn('18', graph)
                    self.assertNotIn('brown eyes', prompt)
                    self.assertNotIn('oval face', prompt)
                    self.assertIn('green cardigan', prompt)
                    self.assertIn('only person', prompt)
                    self.assertIsNone(recipe['lead'])
                else:
                    self.assertEqual(recipe['lead'], 'portrait.png')

    def test_rear_storyboard_filters_face_cues_but_tracks_full_portrait_description(self):
        _, project, first = test_generation_modes.GenerationModesTests().fake()
        project.update(cast='Asha, short black hair, green cardigan, brown eyes', look='Naturalistic live-action',
                       frame_backend='qwen', lead_identity='Short black hair, oval face, brown eyes',
                       lead_identity_of='portrait.png')
        shot = project['shots'][2]
        shot.update(start_frame="Over Asha's shoulder", shot_size='Close-up', start_cast=['Asha'],
                    others='', memory_shot=first['id'], frame_source='storyboard', transition='cut',
                    keyframe=None, video=None, sketch=None, sketches=[], takes={'keyframe':[], 'video':[]})
        worker = object.__new__(studio.Studio)
        worker.lock = threading.RLock()
        worker.load = Mock(return_value=project)
        worker.save = Mock(side_effect=lambda p: p)
        worker._require_plan = Mock(return_value=project)
        worker._render_checked = Mock(return_value=([{'filename':'made.png'}], 9, studio.director.review_result([])))
        worker.comfy = Mock()
        with tempfile.TemporaryDirectory(dir='runtime') as folder:
            worker.path = lambda _: Path(folder)
            worker._draw_sketch(project['id'], shot['id'], lambda _: None)
        drawing = shot['sketches'][-1]
        self.assertNotIn('brown eyes', drawing['prompt'])
        self.assertIn('green cardigan', drawing['prompt'])
        self.assertIn('tight over-the-shoulder framing', drawing['prompt'])
        self.assertEqual(drawing['of']['portrait_identity']['description'], project['lead_identity'])
        self.assertFalse(studio.sketch_stale(project, shot))
        project['lead_identity'] = 'New portrait description'
        self.assertTrue(studio.sketch_stale(project, shot))

    def test_rear_description_recipe_tracks_portrait_changes_without_claiming_image_input(self):
        from test_asset_dependencies import fixture
        project, shot = fixture()
        recipe = studio.current_take(shot, 'keyframe')['recipe']
        recipe.update(lead=None, lead_description_source=project['reference'])
        self.assertFalse(studio.frame_stale(project, shot))
        project['reference'] = 'new-portrait.png'
        self.assertTrue(studio.frame_stale(project, shot))

    def test_written_direction_survives_board_placement_without_overwriting_kept_shots(self):
        rows = ('SHOT: 2 | Tavi takes the cup | Medium | Static | 4 | room tone | lead, Tavi | - | reframe | '
                'Cup in lead hand | Cup in Tavi hand\n'
                'SHOT: 3 | Tavi lifts the cup | Medium | Dolly in | 4 | room tone | Tavi | - | continue | '
                'Cup in Tavi hand | Tavi lifts the cup')
        written = studio.director.parse_shots(rows)
        obj, saved, _ = test_story_pipeline.harness([{'shots': json.dumps(written)}])
        project = obj.load('scratch')
        project['beats'] = ['A cup appears', 'Tavi takes the cup', 'Tavi lifts the cup']
        project['shots'][0].update(beat=1, transition='cut', frame_source='storyboard')
        obj.load = lambda _: copy.deepcopy(project)
        obj._run_write_shots({'project': 'scratch', 'mode': 'board'}, lambda _: None)
        shots = saved[0]['shots']
        self.assertEqual(shots[0]['id'], 'made')
        self.assertEqual((shots[1]['transition'], shots[1]['frame_source']), ('cut', 'previous_end'))
        self.assertEqual(shots[2]['transition'], 'continue')

    def test_first_written_shot_never_depends_on_a_nonexistent_previous_shot(self):
        row = ('SHOT: 1 | The lead opens the door | Wide | Static | 4 | room tone | lead | - | reframe | '
               'Lead by door | Door open')
        obj, saved, _ = test_story_pipeline.harness([{'shots': json.dumps(studio.director.parse_shots(row))}])
        project = obj.load('scratch')
        project['shots'] = []
        project['beats'] = ['The lead opens the door']
        obj.load = lambda _: copy.deepcopy(project)
        obj._run_write_shots({'project': 'scratch', 'mode': 'board'}, lambda _: None)
        first = saved[0]['shots'][0]
        self.assertEqual((first['transition'], first['frame_source']), ('cut', 'storyboard'))

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg not installed')
    def test_extracts_last_decoded_frame(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            path = Path(directory)
            video = path / 'frames.mkv'
            # Red, green, then blue, each one second; lossless encoding avoids colour drift.
            raw = bytes([255, 0, 0] * 4 + [0, 255, 0] * 4 + [0, 0, 255] * 4)
            subprocess.run([studio.ffmpeg(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                            '-s', '2x2', '-r', '1', '-i', '-', '-c:v', 'ffv1', str(video)],
                           input=raw, check=True)
            obj = object.__new__(studio.Studio)
            obj.path = lambda _: path
            last = path / obj._last_frame('scratch', video.name)
            pixel = subprocess.run([studio.ffmpeg(), '-loglevel', 'error', '-i', str(last), '-f', 'rawvideo',
                                    '-pix_fmt', 'rgb24', '-'], capture_output=True, check=True).stdout
            self.assertEqual(pixel[:3], bytes([0, 0, 255]))


if __name__ == '__main__':
    unittest.main()
