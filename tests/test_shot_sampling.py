"""Prove whole-shot sampling is bounded, chronological and truly late-aware."""
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pose_reframe import plan_pose_reframe
from shot_sampling import (DECODE_BUDGET_SECONDS, MAX_FRAMES, MAX_WINDOWS,
                           _window_offsets, sample_rgb_timeline)


class SampleWindowTests(unittest.TestCase):
    def test_short_shots_preserve_single_window(self):
        self.assertEqual(_window_offsets(9.5), ((0.0, 9.5),))
        self.assertEqual(_window_offsets(0), ())
        self.assertEqual(_window_offsets(float("nan")), ())

    def test_long_shots_cover_beginning_and_ending_without_unbounded_decode(self):
        for duration in (15, 19, 40, 90, 3600):
            with self.subTest(duration=duration):
                windows = _window_offsets(duration)
                self.assertLessEqual(len(windows), MAX_WINDOWS)
                self.assertGreaterEqual(len(windows), 2)
                self.assertAlmostEqual(windows[0][0], 0.0)
                self.assertAlmostEqual(sum(length for _, length in windows), 3.5 * len(windows))
                self.assertLessEqual(sum(length for _, length in windows), MAX_FRAMES)
                self.assertAlmostEqual(sum(windows[-1]), duration)
                self.assertEqual(sorted(offset for offset, _ in windows),
                                 [offset for offset, _ in windows])

    def test_timestamps_include_last_part_without_restarting_at_zero(self):
        frame = bytes(320 * 180 * 3)
        offsets = []
        def fake_decoder(source, start, length, timeout):
            offsets.append((start, length, timeout))
            return [frame] * math.ceil(length)
        with patch("shot_sampling._read_proxy_window", side_effect=fake_decoder):
            result = sample_rgb_timeline(Path("clip.mp4"), 5.0, 62)
        self.assertLessEqual(len(result), MAX_FRAMES)
        self.assertTrue(all(isinstance(row, tuple) for row in result))
        timestamps = [t for t, _ in result]
        self.assertEqual(timestamps, sorted(timestamps))
        self.assertGreater(timestamps[-1], 59)
        self.assertEqual(offsets[0][0], 5.0)
        self.assertGreater(offsets[-1][0], 60)

    def test_sampling_failure_keeps_existing_render_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            task = Path(folder) / "pose.task"
            task.write_bytes(b"dummy")
            with patch.dict("os.environ", {"MONTEUR_POSE_MODEL": str(task)}), \
                 patch("pose_reframe._decode_rgb",
                       side_effect=subprocess.TimeoutExpired("ffmpeg", DECODE_BUDGET_SECONDS)):
                result = plan_pose_reframe(Path(folder) / "clip.mp4", 0, 50, 320, 180)
            self.assertIsNone(result)

    def test_true_sample_gap_does_not_trigger_false_occlusion(self):
        with tempfile.TemporaryDirectory() as folder:
            task = Path(folder) / "pose.task"
            task.write_bytes(b"dummy")
            frames = [(float(i), b"f") for i in (0, 1, 2, 30, 31, 32)]
            measured = [(float(i), 0.22, 0.94, None, False, False, 0)
                        for i in (0, 1, 2, 30, 31, 32)]
            with patch.dict("os.environ", {"MONTEUR_POSE_MODEL": str(task)}), \
                 patch("pose_reframe._decode_rgb", return_value=frames), \
                 patch("pose_reframe._infer_poses", return_value=measured):
                result = plan_pose_reframe(Path(folder) / "clip.mp4", 0, 40, 320, 180)
            self.assertIsNotNone(result)
            self.assertEqual(result.mode, "pose_guided")
            self.assertEqual(result.anchors[-1][0], 40)
            self.assertGreater(result.anchors[-2][0], 30)

    def test_big_unobserved_subject_jump_safely_shows_full_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            task = Path(folder) / "pose.task"
            task.write_bytes(b"dummy")
            sampled = [(float(i), b"x") for i in (0, 1, 2, 30, 31, 32)]
            measured = [(float(i), 0.05 if i < 3 else 0.92,
                         0.95, None, False, False, 0)
                        for i in (0, 1, 2, 30, 31, 32)]
            with patch.dict("os.environ", {"MONTEUR_POSE_MODEL": str(task)}), \
                 patch("pose_reframe._decode_rgb", return_value=sampled), \
                 patch("pose_reframe._infer_poses", return_value=measured):
                result = plan_pose_reframe(Path(folder) / "clip.mp4", 0, 40, 320, 180)
            self.assertEqual(result.mode, "composition_safe")


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required for real long-shot sampling")
class LongShotFFmpegTests(unittest.TestCase):
    def test_real_long_video_is_scanned_at_start_and_near_end(self):
        with tempfile.TemporaryDirectory() as folder:
            video = Path(folder) / "long.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "testsrc2=size=320x180:rate=5:duration=29",
                "-c:v", "mpeg4", "-q:v", "7", str(video)
            ], check=True, capture_output=True)
            result = sample_rgb_timeline(video, 0, 29)
            self.assertTrue(result)
            self.assertLessEqual(len(result), MAX_FRAMES)
            times = [t for t, _ in result]
            self.assertLessEqual(times[0], 0.1)
            self.assertGreater(times[-1], 27)
            self.assertTrue(all(len(frame) == 320 * 180 * 3 for _, frame in result))


if __name__ == "__main__":
    unittest.main()
