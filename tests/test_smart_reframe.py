"""Real FFmpeg regressions for conservative, motion-guided vertical framing."""
import math
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from smart_reframe import ReframePlan, ffmpeg_crop_x, plan_vertical_reframe


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg/ffprobe required")
class SmartReframeTests(unittest.TestCase):
    @staticmethod
    def moving_shot(path: Path):
        subprocess.run([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=15:d=9",
            "-f", "lavfi", "-i", "testsrc2=size=50x130:r=15:d=9",
            "-filter_complex", "[0:v][1:v]overlay=x='35+20*t':y=25:shortest=1",
            "-c:v", "mpeg4", "-q:v", "4", str(path)
        ], check=True, capture_output=True)

    def test_tracks_off_center_moving_athlete_proxy(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "moving.mp4"
            self.moving_shot(source)
            plan = plan_vertical_reframe(source, 0, 8, 320, 180)
            self.assertEqual(plan.mode, "motion_guided")
            self.assertGreater(plan.confidence, 0.50)
            self.assertGreater(len(plan.anchors), 3)
            self.assertLess(plan.anchors[0][1], 0.35)
            self.assertGreater(plan.anchors[-1][1], 0.55)
            for (a, x), (b, y) in zip(plan.anchors, plan.anchors[1:]):
                self.assertGreater(b, a)
                self.assertTrue(0 <= x <= 1 and 0 <= y <= 1)
                self.assertLessEqual(abs(y - x), min(0.38, 0.14 * (b - a)) + 1e-6)

            from editor import Clip, render
            output = Path(tmp) / "vertical.mp4"
            metadata = {}
            render(source, output, [Clip(0, 8, 1)], metadata, [],
                   vertical=True, has_audio=False, size=360,
                   source_dimensions=(320, 180))
            self.assertEqual(metadata["auto_reframe"]["motion_guided_clips"], 1)
            dimensions = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0",
                str(output)], text=True).strip()
            self.assertEqual(dimensions, "360,640")
            self.assertGreater(output.stat().st_size, 3000)

    def test_global_animation_is_not_mistaken_for_a_person(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "global.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=4",
                "-c:v", "mpeg4", str(source)
            ], check=True, capture_output=True)
            result = plan_vertical_reframe(source, 0, 3.5, 320, 180)
            self.assertEqual(result.mode, "center_fallback")
            self.assertEqual(ffmpeg_crop_x(result), "(iw-ow)/2")

    def test_failure_and_portrait_source_fall_back_without_stopping_export(self):
        with patch("smart_reframe._sample_gray", side_effect=subprocess.TimeoutExpired("ffmpeg", 35)):
            result = plan_vertical_reframe(Path("missing.mp4"), 0, 4, 320, 180)
            self.assertEqual(result.mode, "center_fallback")
        self.assertEqual(
            plan_vertical_reframe(Path("missing.mp4"), 0, 4, 1080, 1920).mode,
            "center_fallback")
        self.assertEqual(
            plan_vertical_reframe(Path("missing.mp4"), 0, float("nan"), 320, 180).mode,
            "center_fallback")

    def test_crop_expression_is_ffmpeg_safe(self):
        plan = ReframePlan("motion_guided", ((0, 0.1), (2, 0.4), (5, 0.8)), 0.8)
        expression = ffmpeg_crop_x(plan)
        self.assertIn("lt(t\\,", expression)
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "crop.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=15:duration=3",
                "-vf", "scale=180:320:force_original_aspect_ratio=increase,"
                       f"crop=180:320:{expression}:0,setsar=1",
                "-c:v", "mpeg4", str(destination)
            ], check=True, capture_output=True)
            self.assertGreater(destination.stat().st_size, 2000)


if __name__ == "__main__":
    unittest.main()
