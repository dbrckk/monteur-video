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

    def test_no_padding(self):
        self.assertAlmostEqual(sum(allocation([6, 6], automatic_duration([6, 6]))), 10)
        self.assertAlmostEqual(sum(allocation([4, 4], automatic_duration([4, 4]))), 8)

    def test_invalid_sources(self):
        for durations in ([], [0], [float("nan")]):
            with self.assertRaises(ValueError):
                automatic_duration(durations)


if __name__ == "__main__":
    unittest.main()
