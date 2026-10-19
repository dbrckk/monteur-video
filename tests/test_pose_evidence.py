"""Optional pose evidence: bounded, safe and inactive in default production."""
import math
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from pose_evidence import joint_angle, knee_angles, knee_flexion_evidence, analyze_pose


def point(x, y, v=0.96):
    return SimpleNamespace(x=x, y=y, visibility=v)


class PoseEvidenceTests(unittest.TestCase):
    def test_joint_geometry(self):
        self.assertAlmostEqual(joint_angle((0, 1), (0, 0), (1, 0)), 90)
        self.assertAlmostEqual(joint_angle((0, 1), (0, 0), (0, -1)), 180)
        self.assertIsNone(joint_angle((0, 0), (0, 0), (1, 0)))
        self.assertIsNone(joint_angle((math.nan, 1), (0, 0), (1, 0)))

    def test_knee_joint_visibility(self):
        landmarks = [point(0, 0, 0) for _ in range(33)]
        landmarks[23], landmarks[25], landmarks[27] = point(0, 0), point(0, 1), point(1, 1)
        self.assertEqual(len(knee_angles(landmarks)), 1)
        self.assertAlmostEqual(knee_angles(landmarks)[0], 90)
        landmarks[25].visibility = 0.1
        self.assertEqual(knee_angles(landmarks), [])

    def test_real_joint_angle_swing_but_no_fabricated_reps(self):
        frames = [(i, (166 if i % 4 in (0, 3) else 93)) for i in range(12)]
        result = knee_flexion_evidence(frames)
        self.assertTrue(result["detected"])
        self.assertGreater(result["knee_angle_range_degrees"], 60)
        self.assertIsNone(result["repetition_count"])
        self.assertIsNone(result["exercise_classification"])
        self.assertLessEqual(result["confidence"], 0.8)

    def test_flat_sparse_or_insufficient_angles_rejected(self):
        self.assertFalse(knee_flexion_evidence([(i, 165) for i in range(12)])["detected"])
        self.assertFalse(knee_flexion_evidence([(i * 7, 90 if i % 2 else 160)
                                               for i in range(12)])["detected"])
        self.assertFalse(knee_flexion_evidence([(i, 90 if i % 2 else 160)
                                               for i in range(4)])["detected"])

    def test_default_render_requires_no_machine_learning_packages(self):
        with patch.dict(os.environ, {"MONTEUR_ENABLE_POSE": "0"}):
            self.assertEqual(analyze_pose("nonexistent.mp4", 60)["status"], "disabled")


if __name__ == "__main__":
    unittest.main()
