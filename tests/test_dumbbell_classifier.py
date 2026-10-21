"""Conservative ImageNet dumbbell classification and video export tests.

No model/runtime download needed for unit tests; production Docker smoke
verifies the downloaded trained network with a real 224x224 forward pass.
"""
from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dumbbell_classifier import (
    DUMBBELL_IMAGENET_INDEX, _candidate_hands, classify_handheld_dumbbell,
    stable_dumbbell_evidence)
from pose_reframe import plan_pose_reframe
from smart_reframe import ReframePlan


def hand(x=0.30, y=0.50, confidence=0.96):
    pose = [SimpleNamespace(x=0.5, y=0.5, visibility=0.0, presence=0.0)
            for _ in range(33)]
    pose[15] = SimpleNamespace(x=x, y=y, visibility=confidence,
                               presence=confidence)
    return pose


class DumbbellClassificationTests(unittest.TestCase):
    def test_imagenet_label_and_crop_boundary_gate(self):
        self.assertEqual(DUMBBELL_IMAGENET_INDEX, 543)
        self.assertEqual(len(_candidate_hands(hand(0.30), 0.316, 0.5)), 1)
        self.assertEqual(_candidate_hands(hand(0.50), 0.316, 0.5), [])
        self.assertEqual(_candidate_hands(hand(0.30, confidence=0.15), 0.316, 0.5), [])
        self.assertEqual(_candidate_hands(hand(float("nan")), 0.316, 0.5), [])

    def test_requires_repeated_high_confidence_dumbbell(self):
        self.assertFalse(stable_dumbbell_evidence([1.0]))
        self.assertFalse(stable_dumbbell_evidence([0.7, 0, 0, 0, 0]))
        self.assertFalse(stable_dumbbell_evidence([math.nan, 0.9, 0, 0]))
        self.assertTrue(stable_dumbbell_evidence([0.88, 0, 0.91, 0.92, 0, 0]))
        self.assertFalse(stable_dumbbell_evidence([0.67, 0.66, 0.68, 0]))

    def test_invalid_frames_missing_model_and_flag_are_safe(self):
        with patch.dict("os.environ", {"MONTEUR_DUMBBELL_MODEL": "/not/a/model.onnx"}):
            self.assertEqual(classify_handheld_dumbbell(
                bytes(320 * 180 * 3), hand(), 0.316, 0.5), 0)
        with patch.dict("os.environ", {"MONTEUR_DUMBBELL_CLASSIFIER": "0"}):
            self.assertEqual(classify_handheld_dumbbell(
                bytes(320 * 180 * 3), hand(), 0.316, 0.5), 0)
        self.assertEqual(classify_handheld_dumbbell(b"bad", hand(), 0.316, 0.5), 0)

    def test_motion_fallback_remains_after_low_confidence_ml(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / "pose.task"
            model.write_bytes(b"fake")
            options = {"MONTEUR_POSE_MODEL": str(model), "MONTEUR_POSE_REFRAME": "1"}
            for evidence, expected in (
                ([0.94, 0, 0.92, 0.97, 0, 0, 0], "dumbbell_safe"),
                ([0.0, 0, 0.60, 0.0, 0, 0, 0], "pose_guided"),
            ):
                with self.subTest(evidence=evidence), ExitStack() as stack:
                    stack.enter_context(patch.dict("os.environ", options))
                    stack.enter_context(patch("pose_reframe._decode_rgb",
                                              return_value=[b"fake"] * 7))
                    stack.enter_context(patch("pose_reframe._infer_poses",
                                              return_value=[
                                                  (i, 0.19, 0.91, None, False,
                                                   False, evidence[i])
                                                  for i in range(7)]))
                    plan = plan_pose_reframe(Path(tmp) / "video.mp4", 0, 7, 320, 180)
                self.assertIsNotNone(plan)
                self.assertEqual(plan.mode, expected)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg required")
class DumbbellFFmpegTests(unittest.TestCase):
    def test_real_vertical_export_uses_full_scene_for_confident_weight(self):
        from editor import Clip, render
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "source.mp4"
            output = Path(tmp) / "portrait.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=15:duration=2",
                "-c:v", "mpeg4", str(original)
            ], check=True, capture_output=True)
            meta = {}
            with patch("pose_reframe.plan_pose_reframe",
                       return_value=ReframePlan("dumbbell_safe", (), 0.90)):
                render(original, output, [Clip(0, 1.6, 1)], meta, [],
                       vertical=True, has_audio=False, size=360,
                       source_dimensions=(320, 180))
            self.assertEqual(meta["auto_reframe"]["dumbbell_safe_clips"], 1)
            self.assertEqual(meta["auto_reframe"]["center_fallback_clips"], 0)
            dims = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0", str(output)], text=True).strip()
            self.assertEqual(dims, "360,640")
            self.assertGreater(output.stat().st_size, 3000)


if __name__ == "__main__":
    unittest.main()
