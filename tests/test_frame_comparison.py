"""Comparison inputs must match the recorded take, including auxiliary pictures."""
from pathlib import Path
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import compare_frame_editors as comparison


class RecordedFrameInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'runtime')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        for name in ('board.png', 'lead.png', 'prop.png', 'person.png', 'world.png'):
            (self.folder / name).write_bytes(b'fixture')
        self.take = {'prompt':'Use Picture 1 and Picture 2', 'recipe': {
            'kind':'shot', 'frame_source':'storyboard', 'source_frame':'board.png', 'sketch':'board.png',
            'lead':'lead.png', 'world':None, 'world_reference':False, 'character_references':[],
            'visual':{'prop':{}, 'aspect':'16:9'}}}

    def test_lead_then_supporting_character_keeps_recorded_order(self):
        self.take['recipe']['character_references'] = [{'name':'Tavi', 'image':'person.png'}]
        self.take['prompt'] += '; Picture 3 is Tavi'
        paths, aspect = comparison.recorded_inputs(self.folder, self.take)
        self.assertEqual([path.name for path in paths], ['board.png', 'lead.png', 'person.png'])
        self.assertEqual(aspect, '16:9')

    def test_prop_then_world_without_lead_keeps_recorded_order(self):
        recipe = self.take['recipe']
        recipe.update(lead=None, world='world.png', world_reference=True)
        recipe['visual']['prop'] = {'name':'Cup', 'image':'prop.png'}
        self.take['prompt'] = 'Picture 1 is the storyboard; Picture 2 is the cup; Picture 3 is the world'
        paths, _ = comparison.recorded_inputs(self.folder, self.take)
        self.assertEqual([path.name for path in paths], ['board.png', 'prop.png', 'world.png'])

    def test_incomplete_linked_or_unmatched_picture_provenance_is_rejected(self):
        self.take['prompt'] += ' and Picture 3'
        with self.assertRaisesRegex(ValueError, 'missing from the recorded recipe'):
            comparison.recorded_inputs(self.folder, self.take)
        self.take['prompt'] = 'Use Picture 1'
        self.take['recipe']['frame_source'] = 'previous_end'
        with self.assertRaisesRegex(ValueError, 'unsupported reference provenance'):
            comparison.recorded_inputs(self.folder, self.take)
        self.take['recipe']['frame_source'] = 'storyboard'
        del self.take['recipe']['character_references']
        with self.assertRaisesRegex(ValueError, 'incomplete or unsupported'):
            comparison.recorded_inputs(self.folder, self.take)

    def test_reference_cannot_escape_selected_film(self):
        self.take['recipe']['lead'] = '../outside.png'
        with self.assertRaisesRegex(ValueError, 'within the selected film'):
            comparison.recorded_inputs(self.folder, self.take)

    def test_compare_sends_all_recorded_inputs_in_order_and_keeps_qwen_quality(self):
        source = self.folder / 'projects' / 'fixture'
        source.mkdir(parents=True)
        for name in ('board.png', 'lead.png', 'person.png'):
            (source / name).write_bytes(b'fixture')
        self.take['recipe']['character_references'] = [{'name':'Tavi', 'image':'person.png'}]
        self.take['recipe']['visual']['image_quality'] = 'detailed'
        self.take['prompt'] += '; Picture 3 is Tavi'
        self.take['name'] = 'selected.png'
        project = {'shots':[{'keyframe':'selected.png', 'takes':{'keyframe':[self.take]}}]}
        response = lambda *_args, **_kwargs: io.BytesIO(json.dumps(project).encode())
        client = Mock()
        client.upload.side_effect = lambda path: 'uploaded_' + path.name
        client.run.return_value = [{'filename':'output.png'}]
        qwen, klein = Mock(return_value={}), Mock(return_value={})
        output = self.folder / 'output'
        with patch.object(comparison, 'ROOT', self.folder), patch.object(comparison.urllib.request, 'urlopen', response), \
             patch.object(comparison, 'Comfy', return_value=client), \
             patch.object(comparison.graphs, 'coverage_graph', qwen), \
             patch.object(comparison.graphs, 'klein_coverage_graph', klein):
            records = comparison.compare('fixture', 1, [1701], output, 'http://studio', 'http://comfy')
        for build in (qwen, klein):
            self.assertEqual(build.call_args.args[2], 'uploaded_board.png')
            self.assertEqual(build.call_args.kwargs['second_reference'], 'uploaded_lead.png')
            self.assertEqual(build.call_args.kwargs['third_reference'], 'uploaded_person.png')
        self.assertTrue(qwen.call_args.kwargs['detailed'])
        self.assertNotIn('detailed', klein.call_args.kwargs)
        self.assertEqual([record['editor_quality'] for record in records], ['detailed', 'fast'])


if __name__ == '__main__':
    unittest.main()
