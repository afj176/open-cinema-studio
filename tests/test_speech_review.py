import os
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import speech
import studio
import test_draft_pipeline


class SpeechReviewTests(unittest.TestCase):
    def test_not_configured_never_loads_a_model(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(speech, '_model') as load:
            result = speech.check(Path('clip.mp4'), 'Maya: "Hello there"')
        self.assertEqual(result['status'], 'unavailable')
        load.assert_not_called()

    def test_missing_tokenizer_does_not_allow_network_fallback(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            model = Path(directory)
            (model / 'model.bin').write_bytes(b'model')
            with patch.dict(os.environ, {'OPEN_CINEMA_WHISPER_MODEL': str(model)}), patch.object(speech, '_model') as load:
                result = speech.check(model / 'clip.mp4', 'Maya: "Hello there"')
            self.assertEqual(result['status'], 'unavailable')
            load.assert_not_called()

    def test_only_reuses_result_for_same_media_line_and_model(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            model = Path(directory) / 'model'
            model.mkdir()
            (model / 'model.bin').write_bytes(b'model')
            (model / 'tokenizer.json').write_text('{}')
            clip = Path(directory) / 'clip.mp4'
            clip.write_bytes(b'original')
            transcribe = Mock(return_value=([SimpleNamespace(text='Hello there friend')], None))
            with patch.dict(os.environ, {'OPEN_CINEMA_WHISPER_MODEL': str(model)}), patch.object(speech, '_model', return_value=SimpleNamespace(transcribe=transcribe)):
                result = speech.check(clip, 'Maya: "Hello there"')
                self.assertEqual(result['status'], 'possible_match')
                self.assertEqual(speech.check(clip, 'Maya: "Hello there"', result), result)
                self.assertEqual(transcribe.call_count, 1)
                self.assertEqual(speech.check(clip, 'Maya: "Goodbye now"', result)['status'], 'needs_attention')
                clip.write_bytes(b'changed')
                speech.check(clip, 'Maya: "Hello there"', result)
                self.assertEqual(transcribe.call_count, 3)
                self.assertNotIn('transcript', result)

    def test_failure_is_inconclusive_and_does_not_expose_exception(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            model = Path(directory) / 'model'
            model.mkdir()
            (model / 'model.bin').write_bytes(b'model')
            (model / 'tokenizer.json').write_text('{}')
            clip = Path(directory) / 'clip.mp4'
            clip.write_bytes(b'video')
            with patch.dict(os.environ, {'OPEN_CINEMA_WHISPER_MODEL': str(model)}), patch.object(speech, '_model', side_effect=RuntimeError('private path')):
                result = speech.check(clip, 'Maya: "Hello there"')
            self.assertEqual(result['status'], 'unavailable')
            self.assertNotIn('private path', str(result))

    def test_pyav_keyword_mismatch_retries_with_ffmpeg_audio(self):
        audio = object()
        model = SimpleNamespace(transcribe=Mock(side_effect=[
            TypeError("open() got an unexpected keyword argument 'metadata_errors'"),
            ([SimpleNamespace(text='Hello there')], None)]))
        with patch.object(speech, '_ffmpeg_audio', return_value=audio) as decode:
            self.assertEqual(speech._recognized_words(model, Path('clip.mp4')), ['hello', 'there'])
        decode.assert_called_once_with(Path('clip.mp4'))
        self.assertIs(model.transcribe.call_args.args[0], audio)

    def test_other_type_errors_do_not_invoke_fallback(self):
        model = SimpleNamespace(transcribe=Mock(side_effect=TypeError('unrelated')))
        with patch.object(speech, '_ffmpeg_audio') as decode:
            with self.assertRaisesRegex(TypeError, 'unrelated'):
                speech._recognized_words(model, Path('clip.mp4'))
        decode.assert_not_called()

    def test_decoder_failure_is_unavailable_without_exposing_exception(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as directory:
            model = Path(directory) / 'model'; model.mkdir()
            (model / 'model.bin').write_bytes(b'model')
            (model / 'tokenizer.json').write_text('{}')
            clip = Path(directory) / 'clip.mp4'; clip.write_bytes(b'video')
            checker = SimpleNamespace(transcribe=Mock(side_effect=TypeError(
                "open() got an unexpected keyword argument 'metadata_errors'")))
            with patch.dict(os.environ, {'OPEN_CINEMA_WHISPER_MODEL': str(model)}), \
                 patch.object(speech, '_model', return_value=checker), \
                 patch.object(speech, '_ffmpeg_audio', side_effect=speech.AudioDecodeUnavailable('private path')):
                result = speech.check(clip, 'Maya: "Hello there"')
            self.assertEqual(result['status'], 'unavailable')
            self.assertIn('FFmpeg', result['message'])
            self.assertNotIn('private path', str(result))

    @unittest.skipUnless(importlib.util.find_spec('numpy'), 'Speech decoder requires NumPy')
    def test_ffmpeg_fallback_is_bounded_and_produces_mono_float_samples(self):
        result = SimpleNamespace(stdout=b'\x00\x80\x00\x40')
        with patch.object(speech.shutil, 'which', return_value='ffmpeg'), \
             patch.object(speech.subprocess, 'run', return_value=result) as run:
            audio = speech._ffmpeg_audio(Path('a clip.mp4'))
        self.assertEqual(audio.tolist(), [-1.0, 0.5])
        command = run.call_args.args[0]
        self.assertIn('a clip.mp4', command)
        self.assertEqual(command[command.index('-ar') + 1], '16000')
        self.assertEqual(command[command.index('-ac') + 1], '1')
        self.assertEqual(run.call_args.kwargs['timeout'], 120)
        self.assertFalse(run.call_args.kwargs.get('shell', False))

    def test_selection_and_edit_never_show_another_takes_check(self):
        line = 'Maya: "Hello there"'
        result = {'name': 'a.mp4', 'line_hash': speech.line_fingerprint(line), 'script_line': line,
                  'status': 'possible_match', 'message': 'Listen'}
        shot = {'line': line, 'video': 'a.mp4', 'keyframe': 'frame.png', 'quality': {},
                'takes': {'video': [{'name': 'a.mp4', 'dialogue_review': result}, {'name': 'b.mp4'}]}}
        studio.sync_dialogue_review(shot)
        self.assertEqual(shot['quality']['dialogue'], result)
        studio.select_take(shot, 'video', 'b.mp4')
        self.assertNotIn('dialogue', shot['quality'])
        studio.select_take(shot, 'video', 'a.mp4')
        shot['line'] = 'Maya: "Different line"'
        studio.sync_dialogue_review(shot)
        self.assertNotIn('dialogue', shot['quality'])

    def test_video_review_keeps_speech_outcome_separate_from_visual_approval(self):
        worker, project, shot = test_draft_pipeline.DraftPipelineTests().harness()
        shot['line'] = 'Maya: "Hello there"'
        take = studio.current_take(shot, 'video')
        take['of'] = studio.video_inputs(project, shot)
        visual = test_draft_pipeline.review('passed')
        visual['of'] = take['of']
        worker._require_plan = Mock(return_value=project)
        worker._review_video = Mock(return_value=visual)
        with patch.dict(os.environ, {}, clear=True):
            worker._run_review({'project': project['id'], 'shot': shot['id'], 'candidate_name': shot['video']}, lambda _: None)
        self.assertEqual(take['dialogue_review']['status'], 'unavailable')
        self.assertEqual(shot['quality']['dialogue']['status'], 'unavailable')
        self.assertTrue(studio.review_passed(take))


if __name__ == '__main__':
    unittest.main()
