import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_nodes" / "comfyui-open-cinema"))
import graphs
import setup
import studio
import test_story_pipeline


class KleinImageTests(unittest.TestCase):
    def test_klein_coverage_uses_ordered_reference_latents_and_film_canvas(self):
        graph = graphs.klein_coverage_graph('a shot', 23, 'board.png', 'test', '16:9',
                                            second_reference='cast.png', third_reference='world.png')
        self.assertEqual(graph['6']['inputs']['width'], 1280)
        self.assertEqual(graph['6']['inputs']['height'], 704)
        self.assertEqual(graph['7']['inputs']['steps'], 4)
        for index, name in enumerate(('board.png','cast.png','world.png'), 1):
            self.assertEqual(graph[f'ref{index}']['inputs']['image'], name)
            self.assertEqual(graph[f'latent{index}']['inputs']['vae'], ['3', 0])
            self.assertEqual(graph[f'positive{index}']['inputs']['latent'], [f'latent{index}', 0])
        self.assertEqual(graph['positive2']['inputs']['conditioning'], ['positive1', 0])
        self.assertEqual(graph['negative3']['inputs']['conditioning'], ['negative2', 0])
        self.assertEqual(graph['8g']['inputs']['positive'], ['positive3', 0])
        self.assertEqual(graph['8g']['inputs']['negative'], ['negative3', 0])
        with self.assertRaisesRegex(ValueError, 'composition reference'):
            graphs.klein_coverage_graph('a shot', 1, '', 'test', '16:9')
        with self.assertRaisesRegex(ValueError, 'third reference'):
            graphs.klein_coverage_graph('a shot', 1, 'board.png', 'test', '16:9', third_reference='world.png')

    def test_distilled_native_graph_uses_four_steps_and_local_models(self):
        graph = graphs.keyframe_graph("A lighthouse", 17, "16:9", "test", backend="klein")
        self.assertEqual(graph["1"]["inputs"]["unet_name"], "flux-2-klein-4b.safetensors")
        self.assertEqual(graph["2"]["inputs"]["type"], "flux2")
        self.assertEqual(graph["7"]["inputs"]["steps"], 4)
        self.assertEqual(graph["8g"]["inputs"]["cfg"], 1.0)
        self.assertEqual(graph["8n"]["inputs"]["noise_seed"], 17)
        self.assertEqual(graph["10"]["class_type"], "VAEDecode")
        self.assertEqual(graph["11"]["inputs"]["images"], ["10", 0])

    def test_portrait_and_storyboard_use_small_shapes_and_keep_review(self):
        portrait = graphs.keyframe_graph("A person", 1, "16:9", "test", size=graphs.CAST_SIZE, backend="klein")
        self.assertEqual((portrait["6"]["inputs"]["width"], portrait["6"]["inputs"]["height"]), (768, 1024))
        for aspect in graphs.ASPECTS:
            board = graphs.storyboard_graph("A person", 2, aspect, "test", expected_cast=1, backend="klein")
            self.assertEqual((board["6"]["inputs"]["width"], board["6"]["inputs"]["height"]), graphs.KLEIN_SKETCH_SIZES[aspect])
            self.assertEqual(board["11"]["inputs"]["images"], ["mono", 0])
            self.assertEqual(board["cast_review"]["class_type"], "PreviewAny")

    def test_existing_backend_keeps_hidream_and_rejects_unknown(self):
        self.assertEqual(graphs.keyframe_graph("Test", 1, "1:1", "test")["1"]["class_type"], "CheckpointLoaderSimple")
        with self.assertRaisesRegex(ValueError, "supported image backend"):
            graphs.keyframe_graph("Test", 1, "1:1", "test", backend="unknown")

    def test_hidream_preview_reduces_large_images_and_skips_expensive_smoothing(self):
        full = graphs.keyframe_graph("Test", 1, "16:9", "test", size=graphs.CAST_SIZE)
        preview = graphs.keyframe_graph("Test", 1, "16:9", "test", size=graphs.CAST_SIZE, preview=True)
        self.assertEqual((full['6']['inputs']['width'], full['6']['inputs']['height']), graphs.CAST_SIZE)
        self.assertEqual((preview['6']['inputs']['width'], preview['6']['inputs']['height']), graphs.KLEIN_CAST_SIZE)
        self.assertIn('3', full)
        self.assertNotIn('3', preview)
        self.assertEqual(preview['9']['inputs']['model'], ['2', 0])
        world = graphs.keyframe_graph("Test", 1, "16:9", "test", preview=True)
        self.assertEqual((world['6']['inputs']['width'], world['6']['inputs']['height']), graphs.KLEIN_IMAGE_SIZES['16:9'])
        board = graphs.storyboard_graph("Test", 1, "16:9", "test", preview=True)
        self.assertNotIn('3', board)
        self.assertEqual(board['11']['inputs']['images'], ['mono', 0])

    def test_image_backend_is_persisted_and_validated(self):
        worker, saved, _ = test_story_pipeline.harness([])
        worker.create({})
        self.assertEqual(saved[-1]['image_backend'], 'klein')
        worker.update('scratch', {'image_backend': 'hidream'})
        self.assertEqual(saved[-1]['image_backend'], 'hidream')
        with self.assertRaisesRegex(ValueError, 'image backend'):
            worker.update('scratch', {'image_backend': 'unknown'})

    def test_cast_uses_queued_backend_and_preview_in_both_performance_modes(self):
        for mode in ('normal', 'fast'):
            with self.subTest(mode=mode):
                worker, _, _ = test_story_pipeline.harness([])
                project = worker.load('scratch')
                project.update(aspect='16:9', ai_mode=mode, image_backend='hidream', image_quality='fast')
                worker.load = lambda _: project
                worker.comfy.run = Mock(side_effect=RuntimeError('stop after graph submission'))
                with self.assertRaisesRegex(RuntimeError, 'stop after graph submission'):
                    worker._run_cast({'project': 'scratch', 'image_backend': 'klein'}, lambda _: None)
                graph = worker.comfy.run.call_args.args[0]
                self.assertEqual(graph['1']['inputs']['unet_name'], 'flux-2-klein-4b.safetensors')
                self.assertEqual(graph['7']['inputs']['steps'], 4)

    def test_selected_fast_backend_requires_its_models_without_fallback(self):
        service = setup.Setup(type("Client", (), {"server": "http://local"})())
        models = [{**item, "installed": item["group"] != "images_fast"} for item in setup.MANIFEST]
        status = {"connected": True, "missing_nodes": [], "missing_fast_image_nodes": [], "models": models, "ffmpeg": True}
        with patch.object(service, "status", return_value=status):
            service.require("cast", image_backend="hidream")
            with self.assertRaisesRegex(RuntimeError, "flux-2-klein-4b"):
                service.require("cast", image_backend="klein")
        self.assertEqual(len([m for m in models if m["group"] == "images_fast"]), 3)


if __name__ == "__main__":
    unittest.main()
