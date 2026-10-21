"""Video-level gym framing regressions with synthetic bars and visible edges."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from equipment_guard import (FRAME_HEIGHT, FRAME_WIDTH, bar_like_span,
                             stable_wide_bar, wide_limb_span)
from pose_reframe import plan_pose_reframe
from smart_reframe import ReframePlan


def visible_wrists(left=0.36, right=0.64, y=0.50):
    pose = [SimpleNamespace(x=0.5, y=0.5, visibility=0.0, presence=0.0)
            for _ in range(33)]
    for idx, x in ((15, left), (16, right)):
        pose[idx] = SimpleNamespace(x=x, y=y, visibility=0.99, presence=0.99)
    return pose


def synthetic_bar(*, at_y=90):
    frame = bytearray([210, 210, 210] * (FRAME_WIDTH * FRAME_HEIGHT))
    for y in range(at_y, at_y + 3):
        for x in range(12, 310):
            idx = (y * FRAME_WIDTH + x) * 3
            frame[idx:idx + 3] = b"\x16\x16\x16"
    return bytes(frame)


class EquipmentGuardTests(unittest.TestCase):
    def test_detects_long_bar_directly_through_grips(self):
        span = bar_like_span(synthetic_bar(), visible_wrists())
        self.assertIsNotNone(span)
        self.assertLess(span[0], 0.08)
        self.assertGreater(span[1], 0.92)

    def test_background_line_and_uncertain_grips_do_not_count(self):
        self.assertIsNone(bar_like_span(synthetic_bar(at_y=25), visible_wrists()))
        self.assertIsNone(bar_like_span(synthetic_bar(),
                                        visible_wrists(y=0.12)))
        hidden = visible_wrists()
        hidden[15].visibility = 0.12
        self.assertIsNone(bar_like_span(synthetic_bar(), hidden))

    def test_evidence_needs_persistence_and_extra_width(self):
        matches = [(i, 0.25, 0.93, (0.04, 0.97)) for i in range(5)]
        self.assertTrue(stable_wide_bar(matches, 0.316))
        self.assertFalse(stable_wide_bar(matches[:1], 0.316))
        short = [(i, 0.25, 0.93, (0.31, 0.58)) for i in range(5)]
        self.assertFalse(stable_wide_bar(short, 0.316))
        self.assertTrue(wide_limb_span(visible_wrists(0.16, 0.84), 0.316))
        self.assertFalse(wide_limb_span(visible_wrists(0.44, 0.56), 0.316))

    def test_stable_bar_produces_safe_layout_and_unreliable_bar_does_not(self):
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "model.task"
            model.write_bytes(b"mock")
            source = Path(temp) / "source.mp4"
            with patch.dict("os.environ", {"MONTEUR_POSE_MODEL": str(model),
                                            "MONTEUR_POSE_REFRAME": "1"}), \
                 patch("pose_reframe._decode_rgb",
                       return_value=[b"frame"] * 7), \
                 patch("pose_reframe._infer_poses", return_value=[
                     (i, 0.20, 0.91, (0.04, 0.97), False) for i in range(7)]):
                plan = plan_pose_reframe(source, 0, 7, 320, 180)
            self.assertEqual(plan.mode, "equipment_safe")
            with patch.dict("os.environ", {"MONTEUR_POSE_MODEL": str(model),
                                            "MONTEUR_POSE_REFRAME": "1"}), \
                 patch("pose_reframe._decode_rgb",
                       return_value=[b"frame"] * 7), \
                 patch("pose_reframe._infer_poses", return_value=[
                     (i, 0.20, 0.91, (0.04, 0.97) if i == 0 else None, False)
                     for i in range(7)]):
                plan = plan_pose_reframe(source, 0, 7, 320, 180)
            self.assertEqual(plan.mode, "pose_guided")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg required")
class EquipmentSafeExportTests(unittest.TestCase):
    def test_real_vertical_mp4_preserves_both_edges_of_wide_equipment_shot(self):
        from editor import Clip, render
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            original = root / "wide.mp4"
            output = root / "portrait.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i",
                "color=c=gray:s=320x180:r=15:d=2.2,"
                "drawbox=x=0:y=0:w=35:h=180:color=red:t=fill,"
                "drawbox=x=285:y=0:w=35:h=180:color=blue:t=fill",
                "-c:v", "mpeg4", "-q:v", "4", str(original)
            ], check=True, capture_output=True)
            metadata = {}
            with patch("pose_reframe.plan_pose_reframe",
                       return_value=ReframePlan("equipment_safe", (), 0.96)):
                render(original, output, [Clip(0, 2, 1)], metadata, [],
                       vertical=True, has_audio=False, size=360,
                       source_dimensions=(320, 180))
            self.assertEqual(metadata["auto_reframe"]["equipment_safe_clips"], 1)
            self.assertEqual(metadata["auto_reframe"]["center_fallback_clips"], 0)
            dims = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height", "-of", "csv=p=0",
                str(output)], text=True).strip()
            self.assertEqual(dims, "360,640")
            rgb = subprocess.check_output([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                "-i", str(output), "-frames:v", "1",
                "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"])
            self.assertEqual(len(rgb), 360 * 640 * 3)
            def pixel(x, y):
                at = (y * 360 + x) * 3
                return rgb[at:at + 3]
            left = pixel(10, 320)
            right = pixel(350, 320)
            self.assertGreater(left[0], 140, left)
            self.assertLess(left[2], 125, left)
            self.assertGreater(right[2], 135, right)
            self.assertLess(right[0], 135, right)


if __name__ == "__main__":
    unittest.main()
