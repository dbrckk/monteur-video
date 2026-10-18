"""Capture chronology and bounded color matching regression tests."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from color_grade import grade_plan, rush_color_stats
from editor import probe_media
from montage import chronological_order
from visual_quality import VisualSample


def samples(luma, u=128, v=128):
    return [VisualSample(i * .5, luma, 5, 19, u, v) for i in range(12)]


class ColorConsistencyTests(unittest.TestCase):
    def test_bright_and_dark_rushes_converge_safely(self):
        result = grade_plan([samples(67, 117, 142), samples(172, 141, 118)], "fitness")
        grades = result["source_grades"]
        self.assertEqual(result["method"], "robust_per_rush_luminance_chroma")
        self.assertTrue(all(g["measured"] for g in grades))
        self.assertGreater(grades[0]["brightness"], 0)
        self.assertLess(grades[1]["brightness"], 0)
        self.assertLessEqual(max(abs(g["brightness"]) for g in grades), .048)
        self.assertLessEqual(max(abs(g["red_shadows"]) for g in grades), .05)
        self.assertLessEqual(max(abs(g["blue_shadows"]) for g in grades), .05)
        self.assertIn("colorbalance=", grades[0]["filter"])
        self.assertIn("eq=contrast=", grades[1]["filter"])

    def test_shot_level_grading_adapts_within_one_rush(self):
        from editor import Clip
        from color_grade import adaptive_shot_filters
        shots = [*[
            VisualSample(i * .5, 68, 5, 19, 118, 144) for i in range(10)
        ], *[
            VisualSample(5 + i * .5, 169, 5, 19, 139, 115) for i in range(10)
        ]]
        clips = [Clip(0, 5, 3), Clip(5, 10, 3)]
        plan = grade_plan([shots], "fitness")
        filters = adaptive_shot_filters(shots, clips, "fitness", plan)
        self.assertEqual(len(filters), 2)
        self.assertNotEqual(filters[0], filters[1])
        self.assertTrue(all("colorbalance=" in f for f in filters))

    def test_shared_white_balance_applies_across_different_camera_rushes(self):
        from editor import Clip
        from color_grade import adaptive_shot_filters
        first = samples(105, u=114, v=144)
        second = samples(105, u=140, v=114)
        reference = grade_plan([first, second], "fitness")
        self.assertIn("target_u", reference)
        self.assertIn("target_v", reference)
        filter_a = adaptive_shot_filters(first, [Clip(0, 4, 1)],
                                         "fitness", reference, 0)[0]
        filter_b = adaptive_shot_filters(second, [Clip(0, 4, 1)],
                                         "fitness", reference, 1)[0]
        self.assertNotEqual(filter_a, filter_b)
        self.assertIn("colorbalance=rs=-", filter_a)
        self.assertIn("colorbalance=rs=0.", filter_b)

    def test_shot_grade_uses_fallback_without_valid_samples(self):
        from editor import Clip
        from color_grade import adaptive_shot_filters
        clips = [Clip(0, 2, 1), Clip(12, 15, 1)]
        items = samples(105)
        base = grade_plan([items], "fitness")
        filters = adaptive_shot_filters(items, clips, "fitness", base)
        self.assertEqual(filters[1], base["source_grades"][0]["filter"])

    def test_dark_or_unknown_rush_not_forcibly_graded(self):
        result = grade_plan([samples(9), []], "lifestyle")
        self.assertIsNone(result["source_grades"][0]["filter"])
        self.assertIsNone(result["source_grades"][1]["filter"])
        self.assertIsNone(rush_color_stats(samples(9)))


class ChronologyTests(unittest.TestCase):
    def test_capture_timestamp_overrides_intensity_and_upload_order(self):
        with tempfile.TemporaryDirectory() as folder:
            sources = [Path(folder) / (str(i) + ".mp4") for i in range(3)]
            for i, src in enumerate(sources):
                src.write_bytes(bytes([i + 1]) * 100)
            info = [
                {"captured_at": "2026-08-03T09:10:00+00:00"},
                {"captured_at": "2026-08-03T08:30:00+00:00"},
                {"captured_at": "2026-08-03T09:00:00+00:00"},
            ]
            expected = [1, 2, 0]
            order, method = chronological_order(sources, [samples(3), samples(12), samples(8)], info)
            self.assertEqual(order, expected)
            self.assertEqual(method, "capture_time")
            permutation = [2, 0, 1]
            reordered = chronological_order(
                [sources[i] for i in permutation],
                [samples(8), samples(3), samples(12)],
                [info[i] for i in permutation])
            self.assertEqual([sources[permutation[i]] for i in reordered[0]],
                             [sources[i] for i in expected])

    def test_identical_camera_dates_do_not_imply_order(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f"{i}.mp4" for i in range(3)]
            for i, path in enumerate(paths):
                path.write_bytes(bytes([i+1]) * 100)
            order, method = chronological_order(
                paths, [samples(1), samples(8), samples(4)],
                [{"captured_at":"2026-01-01T12:00:00+00:00"} for _ in paths])
            self.assertEqual(method, "visual_continuity_no_reliable_timestamps")
            self.assertEqual(sorted(order), [0, 1, 2])

    def test_android_camera_filenames_reconstruct_order(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f"upload-{i}.mp4" for i in range(3)]
            for i, path in enumerate(paths):
                path.write_bytes(bytes([i+1]) * 100)
            names = ["VID_20260803_143020.mp4", "PXL_20260803_140010.mp4",
                     "VID_20260803_141200.mp4"]
            order, strategy = chronological_order(
                paths, [samples(9), samples(2), samples(5)],
                [{"captured_at": None}] * 3, names)
            self.assertEqual(strategy, "camera_filename_time")
            self.assertEqual(order, [1, 2, 0])

    def test_partial_capture_anchors_keep_known_temporal_order(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f"{i}.mp4" for i in range(4)]
            for i, path in enumerate(paths):
                path.write_bytes(bytes([i+1]) * 100)
            info = [{"captured_at": "2026-01-02T00:00:00+00:00"},
                    {"captured_at": None},
                    {"captured_at": "2026-01-01T00:00:00+00:00"},
                    {"captured_at": None}]
            order, method = chronological_order(
                paths, [samples(9), samples(2), samples(5), samples(7)], info)
            self.assertEqual(method, "capture_anchors_visual_gaps")
            self.assertLess(order.index(2), order.index(0))
            self.assertEqual(sorted(order), list(range(4)))

    def test_partial_dates_do_not_invent_camera_timeline(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder) / f"{i}.mp4" for i in range(3)]
            for i, path in enumerate(paths):
                path.write_bytes(bytes([i + 1]) * 100)
            order, method = chronological_order(paths, [samples(1),samples(5),samples(8)],
                                                  [{"captured_at":None},
                                                   {"captured_at":"2026-05-01T09:00:00+00:00"},
                                                   {"captured_at":None}])
            self.assertEqual(sorted(order), [0,1,2])
            self.assertEqual(method, "visual_continuity_no_reliable_timestamps")


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Requires FFmpeg")
class RealColorRenderTests(unittest.TestCase):
    def test_camera_timestamp_probe_and_grade_filter(self):
        from editor import render, Clip
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "source.mp4"
            destination = folder / "final.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=120x160:r=12:d=2",
                "-metadata", "creation_time=2026-08-03T14:30:00Z",
                "-c:v", "mpeg4", str(source),
            ], check=True, capture_output=True)
            self.assertEqual(probe_media(source)["captured_at"],
                             "2026-08-03T14:30:00+00:00")
            correction = grade_plan([samples(70, 110, 134)], "sport")["source_grades"][0]["filter"]
            metadata = {}
            render(source, destination, [Clip(0, 1.5, 2.0)], metadata, [],
                   True, False, 360, grade_filter=correction)
            self.assertTrue(destination.exists())
            self.assertTrue(1.3 <= probe_media(destination)["duration"] <= 1.8)


if __name__ == "__main__":
    unittest.main()
