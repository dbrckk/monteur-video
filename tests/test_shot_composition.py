"""Automatic pan vs fit-layout regression using actual crop geometry and MP4."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from shot_composition import HorizontalBounds, plan_safe_composition, visible_composition_bounds
from smart_reframe import ffmpeg_crop_x, ReframePlan


def athlete(x=0.30):
    landmarks = [SimpleNamespace(x=x, y=0.5, visibility=0.0, presence=0.0)
                 for _ in range(33)]
    for i, offset in {
        11: -0.035, 12: 0.035, 13: -0.055, 14: 0.055,
        15: -0.090, 16: 0.090, 23: -0.03, 24: 0.03,
        25: -0.040, 26: 0.040, 27: -0.045, 28: 0.045
    }.items():
        landmarks[i] = SimpleNamespace(x=x + offset, y=0.5,
                                        visibility=0.99, presence=0.99)
    return landmarks


class CompositionGeometryTests(unittest.TestCase):
    def test_landmark_bounds_enclose_wrist_gear_bar_and_dumbbell_margin(self):
        base = visible_composition_bounds(athlete(), None, 0)
        self.assertIsNotNone(base)
        self.assertLess(base.left, 0.19)
        self.assertGreater(base.right, 0.41)
        dumbbell = visible_composition_bounds(athlete(), None, 0.94)
        self.assertLess(dumbbell.left, base.left)
        self.assertGreater(dumbbell.right, base.right)
        bar = visible_composition_bounds(athlete(), (0.06, 0.76), 0)
        self.assertLess(bar.left, 0.05)
        self.assertGreater(bar.right, 0.77)

    def test_low_confidence_body_falls_back_without_claiming_boxes(self):
        pts = athlete()
        for item in pts:
            item.visibility = 0
        self.assertIsNone(visible_composition_bounds(pts))
        self.assertIsNone(visible_composition_bounds([]))
        self.assertIsNone(plan_safe_composition([], 5, 0.316))

    def test_fittable_athlete_and_gear_pan_within_crop_not_blurred(self):
        fraction = 0.316
        samples = [(t, 0.7, HorizontalBounds(0.24, 0.49)) for t in range(6)]
        result = plan_safe_composition(samples, 6, fraction)
        self.assertIsNotNone(result)
        self.assertEqual(result.mode, "composition_guided")
        self.assertEqual(result.anchors[-1][0], 6)
        self.assertNotEqual(ffmpeg_crop_x(result), "(iw-ow)/2")
        for t, x in result.anchors:
            if t == 6:
                continue
            left = x * (1 - fraction)
            self.assertLessEqual(left, 0.24 + 0.025)
            self.assertGreaterEqual(left + fraction, 0.49 - 0.025)

    def test_wide_gear_uses_larger_safe_focus_instead_of_full_scene(self):
        samples = [(t, 0.2, HorizontalBounds(0.07, 0.80)) for t in range(6)]
        plan = plan_safe_composition(samples, 6, 0.316)
        self.assertEqual(plan.mode, "composition_focus_safe")
        self.assertEqual(ffmpeg_crop_x(plan), "(iw-ow)/2")
        self.assertLess(plan.safe_bounds[0], 0.07)
        self.assertGreater(plan.safe_bounds[1], 0.80)
        self.assertLess(plan.safe_bounds[1] - plan.safe_bounds[0], 0.84)

    def test_extremely_wide_or_early_only_evidence_preserves_full_source(self):
        almost_full = [(t, 0.2, HorizontalBounds(0.03, 0.95))
                       for t in range(6)]
        self.assertEqual(plan_safe_composition(
            almost_full, 6, 0.316).mode, "composition_safe")
        short_evidence = [(t, 0.2, HorizontalBounds(0.07, 0.80))
                          for t in range(6)]
        self.assertEqual(plan_safe_composition(
            short_evidence, 60, 0.316).mode, "composition_safe")

    def test_sudden_unsafe_pan_selects_full_scene(self):
        sample = [(t, 0.15, HorizontalBounds(0.07, 0.27)) for t in range(3)]
        sample += [(t, 0.85, HorizontalBounds(0.73, 0.93)) for t in range(3, 6)]
        result = plan_safe_composition(sample, 6, 0.316)
        self.assertEqual(result.mode, "composition_safe")

    def test_normal_center_no_special_plan(self):
        samples = [(t, 0.5, HorizontalBounds(0.40, 0.60)) for t in range(6)]
        self.assertIsNone(plan_safe_composition(samples, 6, 0.316))


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg required to validate generated MP4")
class CompositionFFmpegTests(unittest.TestCase):
    def test_render_actual_portrait_mp4_using_composition_track(self):
        from editor import Clip, render
        fraction = 180 * 9 / 16 / 320
        samples = [(float(t), 0.73, HorizontalBounds(0.24, 0.49))
                   for t in range(5)]
        plan = plan_safe_composition(samples, 5, fraction)
        self.assertEqual(plan.mode, "composition_guided")
        with tempfile.TemporaryDirectory() as folder:
            video, result = Path(folder) / "input.mp4", Path(folder) / "result.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "color=c=gray:s=320x180:r=15:d=5,"
                "drawbox=x=78:y=25:w=70:h=130:color=red:t=fill",
                "-c:v", "mpeg4", str(video)
            ], check=True, capture_output=True)
            meta = {}
            with patch("pose_reframe.plan_pose_reframe", return_value=plan):
                render(video, result, [Clip(0, 4.5, 1)], meta, [],
                       vertical=True, has_audio=False, size=360,
                       source_dimensions=(320, 180))
            self.assertEqual(meta["auto_reframe"]["composition_guided_clips"], 1)
            self.assertEqual(meta["auto_reframe"]["composition_safe_clips"], 0)
            self.assertEqual(meta["auto_reframe"]["center_fallback_clips"], 0)
            dims = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0",
                str(result)], text=True).strip()
            self.assertEqual(dims, "360,640")
            self.assertGreater(result.stat().st_size, 3000)

    def test_real_protected_focus_keeps_gear_ends_and_enlarges_subject(self):
        from editor import Clip, render
        # Two colored proxies stand for opposite ends of a piece of equipment.
        # Compared with full-width fit, both ends remain visible but spread
        # much farther across the 360-pixel portrait foreground.
        samples = [(float(t), 0.5, HorizontalBounds(0.24, 0.76))
                   for t in range(5)]
        plan = plan_safe_composition(samples, 5, 0.3164)
        self.assertEqual(plan.mode, "composition_focus_safe")
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "wide.mp4", Path(folder) / "focused.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "color=c=gray:s=320x180:r=15:d=2,"
                "drawbox=x=77:y=0:w=28:h=180:color=red:t=fill,"
                "drawbox=x=215:y=0:w=28:h=180:color=blue:t=fill",
                "-c:v", "mpeg4", str(source)
            ], check=True, capture_output=True)
            meta = {}
            with patch("pose_reframe.plan_pose_reframe", return_value=plan):
                render(source, output, [Clip(0, 1.6, 1)], meta, [],
                       vertical=True, has_audio=False, size=360,
                       source_dimensions=(320, 180))
            self.assertEqual(meta["auto_reframe"]["composition_focus_safe_clips"], 1)
            self.assertEqual(meta["auto_reframe"]["center_fallback_clips"], 0)
            dims = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0",
                str(output)], text=True).strip()
            self.assertEqual(dims, "360,640")
            raw = subprocess.check_output([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                "-i", str(output), "-frames:v", "1", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "pipe:1"])
            def pixel(x):
                i = (320 * 360 + x) * 3
                return raw[i:i + 3]
            # Colored bar ends occupy the near sides of the 9:16 foreground
            # after conservative focus, rather than sitting near its center.
            red, blue = pixel(36), pixel(322)
            self.assertGreater(red[0], 145, red)
            self.assertLess(red[2], 125, red)
            self.assertGreater(blue[2], 145, blue)
            self.assertLess(blue[0], 125, blue)

    def test_too_wide_layout_keeps_both_edges_in_real_video(self):
        from editor import Clip, render
        with tempfile.TemporaryDirectory() as folder:
            video, output = Path(folder) / "wide.mp4", Path(folder) / "safe.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "color=c=gray:s=320x180:r=15:d=2,"
                "drawbox=x=0:y=0:w=35:h=180:color=red:t=fill,"
                "drawbox=x=285:y=0:w=35:h=180:color=blue:t=fill",
                "-c:v", "mpeg4", str(video)
            ], check=True, capture_output=True)
            meta = {}
            with patch("pose_reframe.plan_pose_reframe",
                       return_value=ReframePlan("composition_safe", (), 0.90)):
                render(video, output, [Clip(0, 1.6, 1)], meta, [],
                       vertical=True, has_audio=False, size=360,
                       source_dimensions=(320, 180))
            self.assertEqual(meta["auto_reframe"]["composition_safe_clips"], 1)
            image = subprocess.check_output([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                "-i", str(output), "-frames:v", "1", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "pipe:1"])
            def pixel(x):
                k = (320 * 360 + x) * 3
                return image[k:k + 3]
            left, right = pixel(8), pixel(352)
            self.assertGreater(left[0], 135, left)
            self.assertGreater(right[2], 135, right)


if __name__ == "__main__":
    unittest.main()
