import sys
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / 'app'),
                str(Path(__file__).resolve().parents[1] / 'custom_nodes/comfyui-open-cinema'),
                str(Path(__file__).resolve().parents[1] / 'tools')]
import staging
import director
from benchmark_film_matrix import matrix, execute


class StagingTests(unittest.TestCase):
    def test_back_view_keeps_wardrobe_and_hair_without_facial_details(self):
        source = 'Asha, short black hair, green cardigan, dark brown eyes, a scar on her cheek'
        self.assertEqual(staging.back_view_description(source), 'Asha, short black hair, green cardigan')
        self.assertIsNone(staging.back_view_description('Asha, brown eyes and a red jacket'))
        self.assertIsNone(staging.back_view_description('Asha, brown eyes and a green cardigan'))

    def test_solo_rear_view_needs_explicit_named_lead_and_separable_visible_cues(self):
        people = {'Asha':'Asha, black hair, green cardigan, brown eyes'}
        result = staging.solo_rear_view("Over Asha's shoulder", people, 'Asha', people['Asha'],
                                       'short black hair, dark eyes')
        self.assertEqual(result, ('Asha, black hair, green cardigan', 'short black hair'))
        for opening, roster, lead, cast in [
            ("Not over Asha's shoulder", people, 'Asha', people['Asha']),
            ("Over Jo's shoulder", people, 'Asha', people['Asha']),
            ("Over Asha's shoulder", {**people, 'Jo':'red coat'}, 'Asha', people['Asha']),
            ("Over Asha's shoulder", people, 'Jo', people['Asha']),
            ("Over Asha's shoulder", people, 'Asha', 'Asha, dark eyes and black hair'),
            ("Over Asha's shoulder", people, 'Asha', 'Asha, brown eyes')]:
            self.assertIsNone(staging.solo_rear_view(opening, roster, lead, cast, ''))

    def test_explicit_shoulder_framing_does_not_require_a_face(self):
        opening = "Over Asha's shoulder, facing the empty chair"
        prompt = director.motion_prompt('Asha looks at the chair', 'Static', shot_size='Close-up', start_frame=opening)
        self.assertIn('tight over-the-shoulder framing', prompt)
        self.assertNotIn('close-up on the face', prompt)
        self.assertIn('close-up on the face', director.motion_prompt('Asha smiles', 'Static', shot_size='Close-up'))
        board = director.sketch_prompt('Asha looks at the chair', 'Close-up', lead=True,
                                       cast='Asha, short black hair, green cardigan',
                                       start_frame=opening, expected_cast=1, solo_rear_view=True)
        self.assertIn('tight over-the-shoulder framing', board)
        self.assertIn('back of the head and shoulder', board)
        self.assertNotIn('close-up on the face', board)
        self.assertNotIn('moving deeper into the scene', board)

    def test_named_shoulder_becomes_a_visible_geometry_contract(self):
        people = {'Jo': 'yellow coat', 'Ren': 'blue coat'}
        facts = staging.visual_facts("Over Jo’s shoulder, facing Ren", 'cel animation', people, 'start')
        self.assertEqual(list(facts), ['Jo · camera orientation'])
        self.assertIn('back of the head', facts['Jo · camera orientation'])
        self.assertIn('same individual', staging.camera_direction("Over Jo's shoulder", people))
        self.assertEqual(staging.visual_facts("Over Jo's shoulder", '', people, 'end'), {})

    def test_unknown_ambiguous_and_partial_names_do_not_invent_geometry(self):
        people = {'Jo': 'yellow coat', 'Ren': 'blue coat'}
        for text in ("Over someone's shoulder", "Over Joel's shoulder", "Over Jo's shoulder then over Ren's shoulder",
                     "Not over Jo's shoulder; use a profile instead"):
            self.assertEqual(staging.camera_direction(text, people), '')

    def test_viewpoint_review_respects_explicit_duration_and_ending(self):
        people = {'Jo': 'yellow coat', 'Ren': 'blue coat'}
        opening = "Over Jo's shoulder"
        ending = "Still over Jo's shoulder, facing Ren"
        self.assertEqual(staging.visual_facts(opening, '', people, 'middle', ending), {})
        self.assertIn('Jo · camera orientation', staging.visual_facts(opening, '', people, 'end', ending))
        held = opening + ' throughout the shot'
        self.assertIn('Jo · camera orientation', staging.visual_facts(held, '', people, 'middle', ending))
        self.assertEqual(staging.visual_facts(held, '', people, 'end', 'Jo turns to face the viewer'), {})

    def test_mixed_material_contract_does_not_restyle_a_cartoon_or_puppet_film(self):
        people = {'Jo': 'adult human in blue', 'Pip': 'cloth puppet in green'}
        self.assertEqual(len(staging.material_facts('Live-action photography', people)), 2)
        self.assertEqual(staging.material_facts('2D cel animation', people), {})
        self.assertEqual(staging.material_facts('Cartoon with photographic lighting', people), {})
        self.assertEqual(staging.material_facts('Photorealistic CGI', people), {})
        self.assertEqual(staging.material_facts('Stop-motion, not live-action', people), {})
        self.assertEqual(staging.material_facts('Live-action photography', {'Pip':'cloth puppet'}), {})

    def test_observer_does_not_receive_target_orientation_or_material_value(self):
        expected = {'people': {'Jo': 'yellow coat'}, 'state': {
            'Jo · camera orientation': 'SENTINEL_TARGET', 'Jo · rendering material': 'SENTINEL_MATERIAL'}}
        for key in expected['state']:
            brief = director.fact_observation_brief(key, expected)
            self.assertNotIn('SENTINEL', brief)
        self.assertIn('back of the head', director.fact_observation_brief('Jo · camera orientation', expected))
        self.assertIn('cloth and stitching', director.fact_observation_brief('Jo · rendering material', expected))
        material_brief = director.fact_observation_brief('Jo · rendering material',
            {'people': {'Jo':'a real human with blue shirt', 'Pip':'cloth puppet with red scarf'}})
        self.assertNotIn('a real human', material_brief)
        self.assertNotIn('cloth puppet with', material_brief)

    def test_matrix_has_every_mode_seed_pair_once(self):
        rows = matrix(['a', 'b'], ['fast', 'normal'], [0, 100])
        self.assertEqual(len(rows), 8)
        self.assertEqual(len({row['folder'] for row in rows}), 8)
        for args in [(['../bad'], ['fast'], [0]), (['a'], ['fast'], [0, 0]), (['a'], ['normal'], [-1])]:
            with self.assertRaises(ValueError):
                matrix(*args)

    def test_mixed_composition_requires_both_materials_and_uses_reference_order(self):
        people = {'Jo': 'adult human with blue shirt', 'Pip': 'cloth puppet with green coat'}
        prompt = staging.portrait_composition_prompt('Jo stands beside Pip', 'medium', 'workshop',
                                                    'Live-action photography', people)
        self.assertIn('Picture 1 identifies Jo', prompt)
        self.assertIn('Picture 2 identifies Pip', prompt)
        self.assertIn('Opening pose: Jo stands beside Pip', prompt)
        with self.assertRaises(ValueError):
            staging.portrait_composition_prompt('', '', '', 'cartoon', people)

    def test_spoken_line_binds_to_lead_identity_and_leaves_silent_shots_silent(self):
        prompt = director.motion_prompt('Jo waves', 'Static', cast='Jo, yellow coat', line='Lead: "Hello."')
        self.assertIn('only speaker is Jo, yellow coat', prompt)
        self.assertIn('other visible characters listen silently', prompt)
        self.assertNotIn('only speaker', director.motion_prompt('Jo waves', 'Static', line=''))
        self.assertIn('voice is offscreen', director.motion_prompt('A door opens', 'Static', lead=False,
                                                                 line='Lead: "Hello."'))

    def test_matrix_preserves_outputs_and_does_not_overlap_timed_out_work(self):
        root = Path(__file__).resolve().parents[1]
        cells = matrix(['cel_animation_bus_stop'], ['fast', 'normal'], [0])
        with tempfile.TemporaryDirectory(dir=root / 'runtime') as folder:
            output = Path(folder) / 'matrix'
            with patch('benchmark_film_matrix.subprocess.run', return_value=SimpleNamespace(returncode=2)) as run:
                rows = execute(cells, output, root / 'tests/fixtures/film_pipeline_cases.json',
                               'http://localhost:1', 'http://localhost:2', 'klein', 10)
                self.assertEqual(run.call_count, 1)
                self.assertFalse(rows[0]['pipeline_complete'])
                self.assertEqual(rows[0]['quality'], 'not_assessed')
            saved = (output / 'matrix.json').read_bytes()
            with self.assertRaises(ValueError), patch('benchmark_film_matrix.subprocess.run') as run:
                execute(cells, output, root / 'tests/fixtures/film_pipeline_cases.json', '', '', 'klein', 10)
            run.assert_not_called()
            self.assertEqual((output / 'matrix.json').read_bytes(), saved)
