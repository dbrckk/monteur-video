"""Fast offline guards for an optional, production-disabled detector probe."""
from __future__ import annotations

import unittest
from scripts.benchmark_dfine_cpu import (
    TARGET_CLASSES, _tensor_shape, _memory_mb,
)


class GymBenchmarkGuards(unittest.TestCase):
    def test_expected_objects365_classes_are_explicit(self):
        self.assertEqual(TARGET_CLASSES[323], "Dumbbell")
        self.assertEqual(TARGET_CLASSES[349], "Barbell")
        self.assertEqual(TARGET_CLASSES[332], "Treadmill")

    def test_bounded_rgb_tensor_input(self):
        self.assertEqual(_tensor_shape([1, 3, 640, 640]), (1, 3, 640, 640))
        self.assertEqual(_tensor_shape(["batch", 3, "height", "width"]),
                         (1, 3, 640, 640))
        for shape in ([8, 3, 640, 640], [1, 4, 640, 640],
                      [1, 3, 1024, 1024], [1, 3], [1, 3, 640, 1000]):
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                _tensor_shape(shape)

    def test_peak_rss_measurement_is_available(self):
        self.assertGreater(_memory_mb()["process_peak_mib"], 0)


if __name__ == "__main__":
    unittest.main()
