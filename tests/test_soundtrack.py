"""Music is entirely original; final MP4 must have clear rhythmic audio."""
import math
import shutil
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from soundtrack import SOUND_LEVELS, TRACKS, add_soundtrack, beat_duration, create_original_beat, prepare_instagram_reel
from editor import probe_media


class OriginalMusicTests(unittest.TestCase):
    def test_every_theme_has_original_tempo(self):
        with tempfile.TemporaryDirectory() as root:
            for theme in TRACKS:
                with self.subTest(theme=theme):
                    target = Path(root) / f"{theme}.wav"
                    track = create_original_beat(theme, target, bars=2)
                    self.assertEqual(track["origin"], "original_generated")
                    self.assertTrue(110 <= track["bpm"] <= 155)
                    self.assertAlmostEqual(beat_duration(theme), 60 / track["bpm"])
                    with wave.open(str(target), "rb") as audio:
                        self.assertEqual(audio.getnchannels(), 1)
                        self.assertEqual(audio.getframerate(), 22050)
                        self.assertTrue(2.5 < audio.getnframes() / 22050 < 4.3)
                        self.assertNotEqual(audio.readframes(900), b"\x00" * 1800)
            self.assertEqual(SOUND_LEVELS["low"], 0.2)
            self.assertEqual(SOUND_LEVELS["mute"], 0.0)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "FFmpeg and ffprobe are required")
class MixFFmpegTests(unittest.TestCase):
    @staticmethod
    def video(path: Path) -> None:
        subprocess.run([
            "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=20:duration=2.1",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2.1",
            "-t", "2.1", "-c:v", "mpeg4", "-q:v", "6",
            "-c:a", "aac", str(path)
        ], check=True, capture_output=True)

    def test_all_modes_create_h264_compatible_mp4_with_music(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            for mode, speech, expected_volume in [
                ("auto", False, 0.0), ("auto", True, 0.2),
                ("low", False, 0.2), ("mute", True, 0.0)
            ]:
                with self.subTest(mode=mode, speech=speech):
                    path = work / f"{mode}-{speech}.mp4"
                    self.video(path)
                    before = path.read_bytes()
                    music = add_soundtrack(path, "fitness",
                                           sound_mode=mode, voice_present=speech)
                    self.assertEqual(music["original_audio_volume"], expected_volume)
                    self.assertEqual(music["origin"], "original_generated")
                    self.assertEqual(music["bpm"], 144)
                    self.assertNotEqual(before, path.read_bytes())
                    self.assertTrue(abs(probe_media(path)["duration"] - 2.1) < 0.3)
                    self.assertGreater(path.stat().st_size, 10000)
                    codec = subprocess.check_output([
                        "ffprobe", "-v", "error", "-select_streams", "a:0",
                        "-show_entries", "stream=codec_name",
                        "-of", "csv=p=0", str(path)], text=True).strip()
                    self.assertEqual(codec, "aac")
                    self.assertFalse(list(work.glob("*.partial.mp4")))
                    self.assertFalse(list(work.glob("*.original-beat.wav")))

    def test_instagram_mode_removes_source_audio_without_embedding_a_commercial_track(self):
        with tempfile.TemporaryDirectory() as root:
            file = Path(root) / "reel.mp4"
            self.video(file)
            result = prepare_instagram_reel(file, sound_mode="auto", voice_present=False)
            self.assertFalse(result["music_embedded"])
            self.assertEqual(result["original_audio_volume"], 0)
            self.assertEqual(result["mode"], "instagram_native")
            probe = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "a",
                "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(file)
            ], text=True).strip()
            self.assertEqual(probe, "")
            self.assertTrue(file.stat().st_size > 4000)
            self.video(file)
            result = prepare_instagram_reel(file, sound_mode="low", voice_present=False)
            self.assertEqual(result["original_audio_volume"], 0.2)
            probe = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(file)
            ], text=True).strip()
            self.assertEqual(probe, "aac")

    def test_invalid_sound_mode_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "unknown.mp4"
            path.touch()
            with self.assertRaises(ValueError):
                add_soundtrack(path, "fitness", sound_mode="dangerous")


if __name__ == "__main__":
    unittest.main()
