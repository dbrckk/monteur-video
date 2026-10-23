"""MediaPipe Tasks joint-motion evidence and real edited MP4 regression tests."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from action_story import candidate_pose_score
from editor import edit_video, plan_clips, probe_media
from pose_evidence import analyze_pose, elbow_angles


def point(x, y, visibility=.98, presence=.98):
    return SimpleNamespace(x=x, y=y, visibility=visibility, presence=presence)


class RealJointEvidenceTests(unittest.TestCase):
    def test_arms_are_measured_only_when_both_segments_visible(self):
        points = [point(0, 0, 0, 0) for _ in range(33)]
        points[11], points[13], points[15] = (
            point(0, 0), point(0, 1), point(1, 1))
        found = elbow_angles(points)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0], 90)
        points[15].visibility = .2
        self.assertEqual(elbow_angles(points), [])
        points[15].visibility = .98
        points[15].presence = .1
        self.assertEqual(elbow_angles(points), [])

    def test_model_tasks_cycles_create_bounded_joint_windows_no_rep_claims(self):
        swing = [166, 166, 95, 95, 166, 166, 95, 95]
        measured = [[{"time": float(i), "knee": swing[i], "elbow": None}
                     for i in range(8)]]
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "pose.task"
            model.write_bytes(b"test substitute")
            with patch.dict(os.environ, {
                    "MONTEUR_ENABLE_POSE": "1",
                    "MONTEUR_POSE_MODEL": str(model)}), patch(
                    "pose_evidence._measure_joint_windows",
                    return_value=measured) as infer:
                result = analyze_pose(Path("mock.mp4"), 8)
            infer.assert_called_once()
        self.assertEqual(result["status"], "measured")
        self.assertTrue(result["detected"])
        self.assertEqual(result["motion_intervals"][0]["joint"], "knee")
        self.assertEqual(result["motion_intervals"][0]["kind"],
                         "observed_joint_flexion_extension")
        self.assertLessEqual(result["motion_intervals"][0]["end"], 8)
        self.assertIsNone(result["exercise_classification"])
        self.assertIsNone(result["repetition_count"])

    def test_missing_model_and_inference_error_degrade_without_blocking(self):
        with patch.dict(os.environ, {
                "MONTEUR_ENABLE_POSE": "1",
                "MONTEUR_POSE_MODEL": "/no/such/pose.task"}):
            self.assertEqual(analyze_pose(Path("no.mp4"), 8)["status"],
                             "unavailable")
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "pose.task"
            model.write_bytes(b"stub")
            with patch.dict(os.environ, {
                    "MONTEUR_ENABLE_POSE": "1",
                    "MONTEUR_POSE_MODEL": str(model)}), patch(
                    "pose_evidence._measure_joint_windows",
                    side_effect=RuntimeError("camera unavailable")):
                result = analyze_pose(Path("mock.mp4"), 8)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["reason"], "RuntimeError")

    def test_uncertain_joints_or_unsampled_gaps_never_create_highlights(self):
        sparse = [[{"time": i * 8., "knee": 90 if i % 2 else 166,
                    "elbow": None} for i in range(8)]]
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "pose.task"
            model.write_bytes(b"stub")
            with patch.dict(os.environ, {
                    "MONTEUR_ENABLE_POSE": "1",
                    "MONTEUR_POSE_MODEL": str(model)}), patch(
                    "pose_evidence._measure_joint_windows", return_value=sparse):
                result = analyze_pose(Path("mock.mp4"), 65)
        self.assertFalse(result["detected"])
        self.assertEqual(result["motion_intervals"], [])

    def test_score_only_supports_verified_joint_motion_and_clip_overlap(self):
        valid = [{"start": 0.0, "end": 5.5, "confidence": 0.75,
                  "joint": "elbow", "kind": "observed_joint_flexion_extension"}]
        self.assertGreater(candidate_pose_score(0, 4, valid), .4)
        self.assertEqual(candidate_pose_score(8, 12, valid), 0)
        self.assertEqual(candidate_pose_score(0, 4, [
            {**valid[0], "joint": "unrecognized"}]), 0)
        self.assertEqual(candidate_pose_score(0, 4, [
            {**valid[0], "confidence": .1}]), 0)
        self.assertEqual(candidate_pose_score(0, 4, [
            {**valid[0], "kind": "speech_only"}]), 0)

    def test_selection_prioritizes_joint_motion_without_reordering(self):
        valid = [{"start": 0.0, "end": 5.5, "confidence": .78,
                  "joint": "knee", "kind": "observed_joint_flexion_extension"}]
        base = plan_clips(15, [], [], [], target_seconds=4, allow_short=True)
        enhanced = plan_clips(15, [], [], [], target_seconds=4, allow_short=True,
                              pose_motion_intervals=valid)
        self.assertTrue(base and enhanced)
        self.assertGreater(max(c.score for c in enhanced),
                           max(c.score for c in base))
        self.assertTrue(all(a.start <= b.start for a, b
                            in zip(enhanced, enhanced[1:])))
        self.assertLessEqual(sum(c.duration for c in enhanced), 4.001)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "real ffmpeg render unavailable")
class PoseHighlightRenderTests(unittest.TestCase):
    def test_real_export_uses_measured_window_and_carries_honest_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.mp4"
            destination = Path(temp) / "master.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=s=160x90:r=12:d=12",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-t", "12", "-c:v", "mpeg4", "-q:v", "4",
                "-c:a", "aac", str(source)
            ], check=True, capture_output=True)
            pose = {"status": "measured", "method": "mediapipe_tasks_visible_joints",
                    "motion_intervals": [{"start": 0, "end": 7.5,
                                          "kind": "observed_joint_flexion_extension",
                                          "joint": "knee", "confidence": .75}],
                    "exercise_classification": None, "repetition_count": None}
            with patch("pose_evidence.analyze_pose", return_value=pose):
                result = edit_video(
                    source, destination, theme="fitness", target_seconds=10,
                    aspect="vertical", size=360, transcribe=False)
            self.assertTrue(destination.exists())
            self.assertEqual(probe_media(destination)["width"], 360)
            self.assertTrue(probe_media(destination)["has_audio"])
            self.assertEqual(result["action_story"]["pose_evidence"]["status"],
                             "measured")
            self.assertGreaterEqual(
                result["action_story"]["selected_joint_motion_windows"], 1)
            self.assertFalse(result["action_story"][
                "actual_pose_or_repetition_recognition"])


if __name__ == "__main__":
    unittest.main()
