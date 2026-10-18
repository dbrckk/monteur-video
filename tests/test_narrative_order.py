"""Storyline sequencing must be deterministic regardless of smartphone upload order."""
import tempfile
import unittest
from pathlib import Path

from editor import analysis_windows
from montage import narrative_order
from visual_quality import VisualSample, usable_ranges


class TimelineSamplingTests(unittest.TestCase):
    def test_short_video_is_inspected_whole(self):
        self.assertEqual(analysis_windows(12), [(0.0, 12)])
        self.assertEqual(analysis_windows(24), [(0.0, 24)])

    def test_long_video_is_bounded_and_includes_end(self):
        for duration in (50, 120, 3600):
            with self.subTest(duration=duration):
                windows = analysis_windows(duration)
                self.assertLessEqual(sum(x[1] for x in windows), 24.1)
                self.assertAlmostEqual(windows[0][0], 0, places=2)
                self.assertAlmostEqual(sum(windows[-1]), duration, places=2)
                self.assertTrue(all(x[1] > 0 for x in windows))
                self.assertTrue(all(windows[i][0] < windows[i+1][0]
                                    for i in range(len(windows)-1)))

    def test_sparse_sample_ranges_do_not_bridge_unknown_minutes(self):
        samples = [
            *[VisualSample(i * 0.5, 110, 7, 27) for i in range(8)],
            *[VisualSample(90 + i * 0.5, 110, 7, 27) for i in range(8)],
        ]
        self.assertEqual(usable_ranges(samples, 100), [(0.0, 4.0), (90.0, 94.0)])


class NarrativeOrderTests(unittest.TestCase):
    @staticmethod
    def samples(motion):
        return [VisualSample(i * 0.5, 110, motion, 27) for i in range(12)]

    def test_order_is_independent_of_upload_sequence(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / (name + ".mp4") for name in
                     ("establish", "effort", "climax", "outro")]
            for i, path in enumerate(paths):
                path.write_bytes(bytes([i + 1]) * 257)
            signals = [self.samples(v) for v in (1, 7, 14, 3)]
            original = narrative_order(paths, signals)
            self.assertEqual(original, [0, 1, 2, 3])
            permutation = [2, 3, 0, 1]
            shuffled_paths = [paths[i] for i in permutation]
            shuffled_signals = [signals[i] for i in permutation]
            ordered = narrative_order(shuffled_paths, shuffled_signals)
            self.assertEqual([shuffled_paths[i].name for i in ordered],
                             [paths[i].name for i in original])

    def test_missing_quality_has_stable_content_hash_ties(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f"{i}.mp4" for i in range(3)]
            for i, path in enumerate(paths):
                path.write_bytes(str(i).encode() * 500)
            first = [paths[i].name for i in narrative_order(paths, [[], [], []])]
            shuffled = [paths[i] for i in (2, 0, 1)]
            second = [shuffled[i].name for i in narrative_order(shuffled, [[], [], []])]
            self.assertEqual(first, second)

    def test_short_and_invalid_batches(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "x.mp4"
            file.write_bytes(b"test")
            self.assertEqual(narrative_order([file], [[]]), [0])
            with self.assertRaises(ValueError):
                narrative_order([file], [])


if __name__ == "__main__":
    unittest.main()
