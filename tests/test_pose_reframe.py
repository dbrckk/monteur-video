"""Pose tracking tests: stationary humans, identity continuity and safe fallback."""
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pose_reframe import (_select_person, _smooth_anchors,
                          _target_from_pose, plan_pose_reframe)
from smart_reframe import ffmpeg_crop_x


def person(x: float, visibility: float = 0.98) -> list:
    points = [SimpleNamespace(x=x, y=0.5, visibility=0.0, presence=0.0)
              for _ in range(33)]
    for i, offset in {
        11: -0.035, 12: 0.035, 13: -0.075, 14: 0.075,
        15: -0.12, 16: 0.12, 23: -0.03, 24: 0.03,
        25: -0.07, 26: 0.07, 27: -0.08, 28: 0.08
    }.items():
        points[i] = SimpleNamespace(x=x + offset, y=0.45,
                                    visibility=visibility, presence=visibility)
    return points


class PoseReframeTests(unittest.TestCase):
    def test_stationary_off_center_human_gets_real_pose_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "pose.task"
            model.write_bytes(b"test stub")
            # Person remains nearly still for 8s: old motion tracker could
            # not detect them at all. Model is mocked, crop geometry is real.
            readings = [(i, 0.17, 0.91) for i in range(8)]
            with patch.dict("os.environ", {"MONTEUR_POSE_MODEL": str(model),
                                            "MONTEUR_POSE_REFRAME": "1"}), \\
                 patch("pose_reframe._decode_rgb", return_value=[b"frame"] * 8), \\
                 patch("pose_reframe._infer_poses", return_value=readings):
                plan = plan_pose_reframe(Path(tmp) / "shot.mp4", 0, 8, 320, 180)
            self.assertEqual(plan.mode, "pose_guided")
            self.assertAlmostEqual(plan.anchors[0][1], 0.17)
            self.assertEqual(plan.anchors[-1][0], 8)
            self.assertIn("lt(t\\\\,", ffmpeg_crop_x(plan))
            self.assertGreater(plan.confidence, 0.85)

    def test_pose_landmarks_include_wrists_and_ankles(self):
        crop_fraction = 0.3164
        left = _target_from_pose(person(0.24), crop_fraction)
        right = _target_from_pose(person(0.76), crop_fraction)
        self.assertIsNotNone(left)
        self.assertIsNotNone(right)
        self.assertLess(left[0], 0.25)
        self.assertGreater(right[0], 0.75)
        self.assertGreater(left[1], 0.8)
        self.assertGreater(left[2], 0.2)

    def test_rejects_occluded_body_and_nan_coordinates(self):
        self.assertIsNone(_target_from_pose(person(0.2, visibility=0.1), 0.316))
        bad = person(0.2)
        bad[11].x = float("nan")
        bad[12].x = float("nan")
        bad[23].x = float("nan")
        self.assertIsNone(_target_from_pose(bad, 0.316))

    def test_multi_person_selection_prevents_identity_switching(self):
        people = [person(0.19), person(0.77)]
        result = _select_person(people, 0.316, previous=0.1)
        self.assertLess(result[0], 0.3)
        result2 = _select_person(list(reversed(people)), 0.316, previous=0.9)
        self.assertGreater(result2[0], 0.7)

    def test_smooth_anchors_have_stable_speed_limit(self):
        samples = [(0, 0.05), (1, 1.0), (2, 0.0), (3, 0.9)]
        points = _smooth_anchors(samples, 6)
        self.assertEqual(points[-1][0], 6)
        for (a, x), (b, y) in zip(points, points[1:]):
            self.assertGreater(b, a)
            self.assertLessEqual(abs(y - x), min(0.38, 0.14 * (b - a)) + 1e-6)

    def test_missing_pose_package_or_model_degrades_to_motion(self):
        with patch.dict("os.environ", {"MONTEUR_POSE_MODEL": "/not/a/model.task"}):
            self.assertIsNone(plan_pose_reframe(Path("clip.mp4"), 0, 5, 320, 180))
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "pose.task"
            model.write_bytes(b"stub")
            with patch.dict("os.environ", {"MONTEUR_POSE_MODEL": str(model)}), \\
                 patch("pose_reframe._decode_rgb", return_value=[b"frame"] * 7), \\
                 patch("pose_reframe._infer_poses", side_effect=ImportError):
                self.assertIsNone(plan_pose_reframe(Path("clip.mp4"), 0, 5, 320, 180))
            with patch.dict("os.environ", {"MONTEUR_POSE_MODEL": str(model)}), \\
                 patch("pose_reframe._decode_rgb", return_value=[b"frame"] * 7), \\
                 patch("pose_reframe._infer_poses", return_value=[(1, 0.1, 0.95)]):
                self.assertIsNone(plan_pose_reframe(Path("clip.mp4"), 0, 5, 320, 180))

    def test_disabled_and_portrait_sources(self):
        with patch.dict("os.environ", {"MONTEUR_POSE_REFRAME": "0"}):
            self.assertIsNone(plan_pose_reframe(Path("clip.mp4"), 0, 8, 320, 180))
        self.assertIsNone(plan_pose_reframe(Path("clip.mp4"), 0, 8, 1080, 1920))
        self.assertIsNone(plan_pose_reframe(Path("clip.mp4"), 0, math.nan, 320, 180))


if __name__ == "__main__":
    unittest.main()
