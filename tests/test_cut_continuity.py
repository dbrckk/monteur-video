"""Inspect encoded MP4 boundaries and verify safe multi-rush resequencing."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cut_continuity import optimize_rendered_order
from editor import probe_media
from montage import edit_many


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg and ffprobe required for real MP4 verification")
class RenderedCutContinuityTests(unittest.TestCase):
    @staticmethod
    def make_video(path: Path, color: str) -> None:
        subprocess.run([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=360x640:r=12:d=1.5",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-t", "1.5", "-c:v", "libx264", "-threads", "2",
            "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "96k", str(path)
        ], check=True, capture_output=True)

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        self.paths = [root / f"rush-{i}.mp4" for i in range(5)]
        for path, color in zip(self.paths, ("red", "blue", "red", "blue", "blue")):
            self.make_video(path, color)

    def test_encoded_cut_colors_reorder_interior_not_open_or_close(self):
        durations = [probe_media(path)["duration"] for path in self.paths]
        order, quality = optimize_rendered_order(self.paths, durations)
        self.assertEqual(order, [0, 2, 1, 3, 4])
        self.assertTrue(quality["evaluated"])
        self.assertTrue(quality["reordered"])
        self.assertTrue(quality["protected_first_last"])
        self.assertLess(quality["boundary_color_jump_after"],
                        quality["boundary_color_jump_before"])
        self.assertGreater(quality["boundary_color_jump_before"] -
                           quality["boundary_color_jump_after"], 10)

    def test_unsupported_or_unreadable_media_preserves_original_order(self):
        ordered, report = optimize_rendered_order(self.paths[:4], [1.5] * 4)
        self.assertEqual(ordered, [0, 1, 2, 3])
        self.assertFalse(report["evaluated"])
        corrupted = self.paths.copy()
        corrupted[2] = Path(self.folder.name) / "does-not-exist.mp4"
        ordered, report = optimize_rendered_order(corrupted, [1.5] * 5)
        self.assertEqual(ordered, list(range(5)))
        self.assertEqual(report["reason"], "edge_decode_unavailable")

    def test_full_multi_rush_master_uses_new_order_and_correct_metadata(self):
        def copied_edit(source, destination, **kwargs):
            shutil.copyfile(source, destination)
            return {"rendered_duration_seconds": probe_media(destination)["duration"],
                    "clips": [{"start": 0, "end": 1.5, "score": 1.0}],
                    "selected_transcript": [],
                    "speech_engine": "disabled",
                    "action_quality": {},
                    "auto_reframe": {},
                    "visual_analysis": "unavailable"}

        dest = Path(self.folder.name) / "assembled.mp4"
        fake_grades = {"source_grades": [
            {"filter": None, "correction": None} for _ in self.paths]}
        with (patch("montage.detect_scenes", return_value=[]),
              patch("montage.analyze_visual", return_value=[]),
              patch("montage.grade_plan", return_value=fake_grades),
              patch("montage.select_music_profile",
                    return_value={"bpm": 144, "energy": "high"}),
              patch("montage.chronological_order",
                    return_value=(list(range(5)),
                                  "visual_continuity_no_reliable_timestamps")),
              patch("montage.edit_video", side_effect=copied_edit)):
            result = edit_many(self.paths, dest, target_seconds=10,
                               aspect="vertical", size=360, transcribe=False)
        self.assertEqual(result["sequence_order"], [0, 2, 1, 3, 4])
        self.assertTrue(result["cut_continuity"]["reordered"])
        self.assertEqual([d["index"] for d in result["sources"]],
                         [0, 2, 1, 3, 4])
        self.assertEqual([d["sequence_position"] for d in result["sources"]],
                         list(range(5)))
        self.assertEqual([x["source_index"] for x in result["clips"]],
                         [0, 2, 1, 3, 4])
        self.assertEqual([x["sequence_position"] for x in result["clips"]],
                         list(range(5)))
        self.assertEqual((probe_media(dest)["width"], probe_media(dest)["height"]),
                         (360, 640))
        self.assertTrue(probe_media(dest)["has_audio"])
        self.assertAlmostEqual(probe_media(dest)["duration"], 7.5, delta=0.25)
        self.assertEqual(list(Path(self.folder.name).glob(".assembled-rushes-*")), [])

    def test_captured_timestamp_sequence_is_never_overridden(self):
        def copied_edit(source, destination, **kwargs):
            shutil.copyfile(source, destination)
            return {"rendered_duration_seconds": 1.5, "clips": [],
                    "selected_transcript": [], "speech_engine": "disabled",
                    "action_quality": {}, "auto_reframe": {},
                    "visual_analysis": "unavailable"}
        fake_grades = {"source_grades": [
            {"filter": None, "correction": None} for _ in self.paths]}
        destination = Path(self.folder.name) / "chronological.mp4"
        with (patch("montage.detect_scenes", return_value=[]),
              patch("montage.analyze_visual", return_value=[]),
              patch("montage.grade_plan", return_value=fake_grades),
              patch("montage.select_music_profile", return_value={"bpm": 144}),
              patch("montage.chronological_order",
                    return_value=(list(range(5)), "capture_time")),
              patch("montage.edit_video", side_effect=copied_edit)):
            result = edit_many(self.paths, destination, target_seconds=10,
                               aspect="vertical", size=360, transcribe=False)
        self.assertEqual(result["sequence_order"], list(range(5)))
        self.assertFalse(result["cut_continuity"]["evaluated"])
        self.assertTrue(destination.is_file())


if __name__ == "__main__":
    unittest.main()
