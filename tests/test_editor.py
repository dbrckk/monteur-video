import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from editor import Clip, active_ranges, create_captions, edit_video, plan_clips, social_metadata


class PlanningTests(unittest.TestCase):
    def test_activity_excludes_silences(self):
        self.assertEqual(active_ranges(15, [(2, 5), (9, 12)]),
                         [(0.0, 2), (5, 9), (12, 15)])

    def test_clip_bounds_and_order(self):
        clips = plan_clips(120, [5, 20, 48, 75], [(6, 12)], [], 30)
        self.assertTrue(clips)
        self.assertLessEqual(sum(x.duration for x in clips), 30.001)
        self.assertEqual(clips, sorted(clips, key=lambda c: c.start))
        for clip in clips:
            self.assertGreater(clip.duration, 0)
            self.assertLessEqual(clip.end, 120)

    def test_no_invented_activity_tags(self):
        info = social_metadata("fitness", [], 500)
        self.assertIn("fitness", info["hashtags"])
        self.assertNotIn("squat", info["hashtags"])
        self.assertFalse(info["transcript_used"])

    def test_spoken_keywords_are_evidenced(self):
        info = social_metadata("fitness",
                               [{"start": 1, "end": 3, "text": "Je fais des squats et du cardio"}], 50)
        self.assertIn("squat", info["hashtags"])
        self.assertIn("cardio", info["hashtags"])
        self.assertTrue(info["transcript_used"])

    def test_caption_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "caption.ass"
            self.assertTrue(create_captions(dest, Clip(2, 8, 1),
                            [{"start": 2, "end": 4, "text": "Reste {focus} aujourd'hui"}], True))
            self.assertIn("Dialogue: ", dest.read_text())
            self.assertNotIn("{focus}", dest.read_text())


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg absent")
class IntegrationTests(unittest.TestCase):
    def test_real_vertical_and_landscape_export(self):
        with tempfile.TemporaryDirectory() as temp:
            src = Path(temp) / "original.mp4"
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                 "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=15",
                 "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                 "-t", "6", "-c:v", "mpeg4", "-q:v", "4",
                 "-c:a", "aac", str(src)], check=True)
            for aspect, target in (("vertical", "360,640"), ("youtube", "640,360")):
                dest = Path(temp) / f"{aspect}.mp4"
                meta = edit_video(src, dest, aspect=aspect, target_seconds=10,
                                  transcribe=False, size=360)
                self.assertTrue(dest.is_file())
                self.assertGreater(dest.stat().st_size, 1000)
                probe = subprocess.check_output(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=width,height",
                     "-of", "csv=p=0", str(dest)], text=True).strip()
                self.assertEqual(probe, target)
                self.assertFalse(meta["captions_generated"])
                self.assertGreater(meta["rendered_duration_seconds"], 0)
