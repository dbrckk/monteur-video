import os
import sys
from types import SimpleNamespace
from unittest.mock import patch
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from editor import (Clip, active_ranges, create_captions, edit_video, plan_clips,
                    social_metadata, load_whisper_model, speech_to_text)


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

    def test_long_recording_covers_late_highlights(self):
        clips = plan_clips(3600, [], [], [], 45)
        self.assertGreater(len(clips), 4)
        self.assertGreater(max(x.start for x in clips), 3000)
        self.assertLess(min(x.start for x in clips), 600)
        self.assertLessEqual(sum(x.duration for x in clips), 45.01)

    def test_reject_invalid_target(self):
        with self.assertRaises(ValueError):
            plan_clips(100, [], [], [], 181)

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

    def test_whisper_model_reused_across_multiple_rushes(self):
        constructions = []
        class FakeWhisper:
            def __init__(self, model_name, device, compute_type):
                constructions.append((model_name, device, compute_type))
            def transcribe(self, path, **kwargs):
                return [SimpleNamespace(
                    start=0.2, end=1.6, text="  Je continue ma progression  ")], None
        load_whisper_model.cache_clear()
        try:
            with patch.dict(sys.modules, {
                    "faster_whisper": SimpleNamespace(WhisperModel=FakeWhisper)
            }), patch.dict(os.environ, {"WHISPER_MODEL": "tiny",
                                        "WHISPER_DEVICE": "cpu"}):
                a, engine_a = speech_to_text(Path("first.mp4"))
                b, engine_b = speech_to_text(Path("second.mp4"))
                self.assertEqual((engine_a, engine_b), ("whisper", "whisper"))
                self.assertEqual(a, b)
                self.assertEqual(len(constructions), 1)
        finally:
            load_whisper_model.cache_clear()

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
