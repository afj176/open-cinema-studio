"""Card rendering preserves deterministic pixels while reusing static background work."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

try:
    import numpy as np
    import PIL  # noqa: F401
except ImportError:
    np = None

if np is not None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'custom_nodes' / 'comfyui-open-cinema'))
    import motion


@unittest.skipIf(np is None, 'Motion renderer requires the ComfyUI NumPy/Pillow environment')
class MotionCardsTests(unittest.TestCase):
    def test_precomputed_background_matches_original_formula_and_random_sequence(self):
        width, height = 64, 48
        style = motion.style_for('None')
        base = np.array(motion.rgb(style.bg)[:3], dtype=np.float32) / 255.0
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        d = np.sqrt(((xx - width / 2) / (width * 0.7)) ** 2 + ((yy - height / 2) / (height * 0.7)) ** 2)
        lift = np.clip(1 - d, 0, 1)[..., None] * 0.06
        expected_rng, actual_rng = np.random.default_rng(5), np.random.default_rng(5)
        cached = motion._card_background_base(width, height, style)
        for _ in range(3):
            grain = expected_rng.normal(0, 0.018, (height, width, 1)).astype(np.float32)
            expected = np.clip(base + lift + grain, 0, 1)
            actual = motion._card_background(width, height, style, actual_rng, cached)
            np.testing.assert_array_equal(actual, expected)

    def test_cards_keep_deterministic_frame_shape_range_and_static_base_reuse(self):
        with patch.object(motion, '_card_background_base', wraps=motion._card_background_base) as make_base:
            first = motion.cards(['HELLO', 'THE END'], 8, 160, 96, 'None', 0.5,
                                 labels=['TITLE', 'FIN'], seed=7)
            self.assertEqual(make_base.call_count, 1)
        repeat = motion.cards(['HELLO', 'THE END'], 8, 160, 96, 'None', 0.5,
                              labels=['TITLE', 'FIN'], seed=7)
        np.testing.assert_array_equal(first, repeat)
        self.assertEqual(first.shape, (8, 96, 160, 3))
        self.assertEqual(first.dtype, np.float32)
        self.assertTrue(np.isfinite(first).all())
        self.assertGreaterEqual(first.min(), 0)
        self.assertLessEqual(first.max(), 1)
        self.assertFalse(np.array_equal(first[0], first[-1]))


if __name__ == '__main__':
    unittest.main()
