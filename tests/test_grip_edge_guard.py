"""Regression coverage for unilateral, offset-height and partially hidden grips."""
import math
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from equipment_guard import grip_crop_risk, stable_grip_crop_risk, wide_limb_span
from pose_reframe import plan_pose_reframe
from smart_reframe import ReframePlan


def hand_pose(left=0.09, right=0.48, *, confidence_left=0.99,
              confidence_right=0.99, y_left=0.2, y_right=0.68):
    points = [SimpleNamespace(x=0.5, y=0.5, visibility=0.0, presence=0.0)
              for _ in range(33)]
    for index, x, y, confidence in (
            (15, left, y_left, confidence_left),
            (16, right, y_right, confidence_right)):
        points[index] = SimpleNamespace(x=x, y=y, visibility=confidence,
                                        presence=confidence)
    return points


class GripEdgeSafetyTests(unittest.TestCase):
    def test_unilateral_hand_risk_when_other_hand_not_visible(self):
        points = hand_pose(confidence_right=0.10)
        self.assertFalse(wide_limb_span(points, 0.316))
        self.assertTrue(grip_crop_risk(points, 0.316, 0.48))
        self.assertFalse(grip_crop_risk(hand_pose(0.47, 0.53), 0.316, 0.50))
        self.assertFalse(grip_crop_risk(points, 0.316, math.nan))
        points[15].visibility = 0.08
        self.assertFalse(grip_crop_risk(points, 0.316, 0.48))

    def test_temporal_consensus_rejects_transient_arm_reaches(self):
        self.assertFalse(stable_grip_crop_risk([True, False, False, False]))
        self.assertTrue(stable_grip_crop_risk([True, True, True, False, True]))
        self.assertFalse(stable_grip_crop_risk([True, True]))
        self.assertFalse(stable_grip_crop_risk([]))

    def test_asymmetric_grip_mode_and_normal_pose_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "pose.task"
            model.write_bytes(b"mock")
            env = {"MONTEUR_POSE_MODEL": str(model), "MONTEUR_POSE_REFRAME": "1"}
            for flagged, expected in [
                ([True, True, False, True, True, False, True], "grip_edge_safe"),
                ([True, False, False, False, False, False, True], "pose_guided")
            ]:
                with self.subTest(flagged=flagged), ExitStack() as stack:
                    stack.enter_context(patch.dict("os.environ", env))
                    stack.enter_context(patch("pose_reframe._decode_rgb",
                                              return_value=[b"frame"] * 7))
                    stack.enter_context(patch("pose_reframe._infer_poses",
                                              return_value=[
                                                  (i, 0.22, 0.95, None, False, flagged[i])
                                                  for i in range(7)]))
                    plan = plan_pose_reframe(Path(directory) / "video.mp4",
                                             0, 7, 320, 180)
                self.assertIsNotNone(plan)
                self.assertEqual(plan.mode, expected)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg needed for full video regression")
class GripEdgeFFmpegTests(unittest.TestCase):
    def test_safe_layout_exports_actual_vertical_mp4(self):
        from editor import Clip, render
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "single_dumbbell.mp4"
            output = Path(folder) / "safe_reel.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=15:duration=2",
                "-c:v", "mpeg4", str(source)
            ], check=True, capture_output=True)
            info = {}
            with patch("pose_reframe.plan_pose_reframe",
                       return_value=ReframePlan("grip_edge_safe", (), 0.95)):
                render(source, output, [Clip(0, 1.6, 1)], info, [],
                       vertical=True, has_audio=False, size=360,
                       source_dimensions=(320, 180))
            self.assertEqual(info["auto_reframe"]["grip_edge_safe_clips"], 1)
            self.assertEqual(info["auto_reframe"]["center_fallback_clips"], 0)
            dimensions = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0",
                str(output)], text=True).strip()
            self.assertEqual(dimensions, "360,640")
            self.assertGreater(output.stat().st_size, 3000)


if __name__ == "__main__":
    unittest.main()
