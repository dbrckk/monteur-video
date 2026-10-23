"""Protect evidence-backed action stages across final multirush MP4 cuts."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from action_story import selected_motion_profile
from cut_continuity import optimize_rendered_order
from editor import Clip, probe_media
from montage import edit_many


@dataclass
class Sample:
    time: float
    motion: float
    luminance: float = 110.0
    detail: float = 20.0


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.samples = [Sample(i * 0.5, 12.0 if 8 <= i < 20 else 1.0)
                        for i in range(28)]
        self.bouts = [{"start": 4.0, "end": 10.0, "confidence": 0.76,
                       "kind": "observed_motion_bout"}]

    def test_classify_only_selected_measured_frames(self):
        active = selected_motion_profile(
            [Clip(4, 9.5, 1)], self.samples, self.bouts)
        quiet = selected_motion_profile(
            [Clip(0, 3, 1)], self.samples, self.bouts)
        self.assertEqual(active["phase"], "observed_effort")
        self.assertEqual(quiet["phase"], "measured_low_motion")
        self.assertGreater(active["measured_fraction"], 0.7)
        self.assertEqual(quiet["observed_effort_ratio"], 0.0)
        self.assertTrue(active["not_exercise_or_recovery_recognition"])

    def test_sparse_timeline_and_frozen_footage_never_invent_recovery(self):
        sparse = [Sample(t, 1) for t in (0, .5, 1, 1.5, 100, 100.5, 101, 101.5)]
        self.assertEqual(selected_motion_profile(
            [Clip(0, 102, 1)], sparse, self.bouts)["phase"], "unknown")
        frozen = [Sample(i * 0.5, 0) for i in range(16)]
        self.assertNotEqual(selected_motion_profile(
            [Clip(0, 7, 1)], frozen, [])["phase"], "measured_low_motion")
        self.assertEqual(selected_motion_profile([], self.samples, self.bouts)["phase"],
                         "unknown")
        self.assertEqual(selected_motion_profile(
            [{"start": 4.0, "end": 9.5}], self.samples, self.bouts)["phase"],
                         "observed_effort")

    def test_overlap_and_untrusted_bouts_do_not_fake_action(self):
        invalid = [{**self.bouts[0], "confidence": 0.1}]
        self.assertNotEqual(selected_motion_profile(
            [Clip(4, 9.5, 1)], self.samples, invalid)["phase"],
            "observed_effort")
        duplicated = [self.bouts[0], {**self.bouts[0]}]
        result = selected_motion_profile(
            [Clip(4, 9.5, 1)], self.samples, duplicated)
        self.assertEqual(result["observed_effort_ratio"], 1.0)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "Actual FFmpeg required")
class RealPhaseSequenceTests(unittest.TestCase):
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
        for path, color in zip(self.paths,
                               ("red", "blue", "red", "blue", "blue")):
            self.make_video(path, color)

    def test_actual_rgb_improvement_cannot_override_observed_phase_order(self):
        duration = [1.5] * 5
        baseline, plain = optimize_rendered_order(self.paths, duration)
        self.assertEqual(baseline, [0, 2, 1, 3, 4])
        profiles = [{"phase": stage} for stage in (
            "measured_low_motion", "observed_effort", "measured_low_motion",
            "observed_effort", "measured_low_motion")]
        protected, report = optimize_rendered_order(
            self.paths, duration, phase_profiles=profiles)
        self.assertEqual(protected, list(range(5)))
        self.assertTrue(report["phase_guard_enabled"])
        self.assertFalse(report["reordered"])
        self.assertGreater(report["phase_protected_transitions"], 0)
        self.assertLess(plain["boundary_color_jump_after"],
                        report["boundary_color_jump_after"])

    def test_all_unknown_profiles_keep_safe_existing_rgb_fallback(self):
        all_unknown = [{"phase": "unknown"}] * 5
        ordering, report = optimize_rendered_order(
            self.paths, [1.5] * 5, phase_profiles=all_unknown)
        self.assertEqual(ordering, [0, 2, 1, 3, 4])
        self.assertFalse(report["phase_guard_enabled"])

    def test_full_export_keeps_phase_sequence_and_complete_metadata(self):
        phases = ["measured_low_motion", "observed_effort",
                  "measured_low_motion", "observed_effort",
                  "measured_low_motion"]
        def copied_edit(source, destination, **kwargs):
            shutil.copyfile(source, destination)
            index = self.paths.index(source)
            return {"rendered_duration_seconds": probe_media(destination)["duration"],
                    "clips": [{"start": 0, "end": 1.5, "score": 1}],
                    "selected_transcript": [],
                    "speech_engine": "disabled",
                    "action_quality": {},
                    "action_story": {"selected_motion_profile": {
                        "phase": phases[index], "measured_fraction": 0.95}},
                    "auto_reframe": {},
                    "visual_analysis": "unavailable"}
        fake_grades = {"source_grades": [
            {"filter": None, "correction": None} for _ in self.paths]}
        dest = Path(self.folder.name) / "phase-master.mp4"
        with (patch("montage.detect_scenes", return_value=[]),
              patch("montage.analyze_visual", return_value=[]),
              patch("montage.grade_plan", return_value=fake_grades),
              patch("montage.select_music_profile", return_value={"bpm": 144}),
              patch("montage.chronological_order",
                    return_value=(list(range(5)),
                                  "visual_continuity_no_reliable_timestamps")),
              patch("montage.edit_video", side_effect=copied_edit)):
            result = edit_many(self.paths, dest, target_seconds=10,
                               aspect="vertical", size=360, transcribe=False)
        self.assertEqual(result["sequence_order"], [0, 1, 2, 3, 4])
        self.assertEqual(result["selected_motion_phase_order"], phases)
        self.assertTrue(result["cut_continuity"]["phase_guard_enabled"])
        self.assertEqual([part["sequence_position"] for part in result["sources"]],
                         list(range(5)))
        self.assertEqual((probe_media(dest)["width"], probe_media(dest)["height"]),
                         (360, 640))
        self.assertAlmostEqual(probe_media(dest)["duration"], 7.5, delta=0.25)
        self.assertFalse(list(Path(self.folder.name).glob(".phase-master-rushes-*")))


if __name__ == "__main__":
    unittest.main()
