"""Regression tests for adaptive short-form montage targets."""
import unittest
from montage import automatic_duration, allocation


class AutomaticDurationTests(unittest.TestCase):
    def test_short_footage(self):
        self.assertEqual(automatic_duration([8]), 10)
        self.assertEqual(automatic_duration([12]), 10)
        self.assertEqual(automatic_duration([15]), 15)
        self.assertEqual(automatic_duration([8, 8]), 15)

    def test_long_footage(self):
        self.assertEqual(automatic_duration([25]), 15)
        self.assertEqual(automatic_duration([50]), 30)
        self.assertEqual(automatic_duration([80]), 45)
        self.assertEqual(automatic_duration([180]), 60)

    def test_scene_aware_short_reels(self):
        self.assertEqual(automatic_duration([120], [45]), 15)
        self.assertEqual(automatic_duration([120], [22]), 30)
        self.assertEqual(automatic_duration([120], [0]), 60)
        self.assertEqual(automatic_duration([80], [25]), 15)
        self.assertEqual(automatic_duration([50], [9]), 30)

    def test_invalid_scene_analysis(self):
        for counts in ([], [-1], [1, 2]):
            with self.assertRaises(ValueError):
                automatic_duration([80], counts)

    def test_motion_burst_makes_long_footage_short(self):
        self.assertEqual(automatic_duration([180], [0], activity_seconds=8), 10)
        self.assertEqual(automatic_duration([180], [0], activity_seconds=15), 15)
        self.assertEqual(automatic_duration([180], [0], activity_seconds=35), 60)
        self.assertEqual(automatic_duration([180], [45], activity_seconds=8), 10)

    def test_invalid_motion_activity(self):
        for activity in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                automatic_duration([120], activity_seconds=activity)

    def test_no_padding(self):
        self.assertAlmostEqual(sum(allocation([6, 6], automatic_duration([6, 6]))), 10)
        self.assertAlmostEqual(sum(allocation([4, 4], automatic_duration([4, 4]))), 8)

    def test_invalid_sources(self):
        for durations in ([], [0], [float("nan")]):
            with self.assertRaises(ValueError):
                automatic_duration(durations)


if __name__ == "__main__":
    unittest.main()
