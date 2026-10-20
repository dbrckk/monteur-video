"""Music is entirely original; final MP4 must have clear rhythmic audio."""
import math
import array
import shutil
import subprocess
import tempfile
import unittest
import wave
from unittest.mock import patch
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

    def test_duck_generated_music_during_source_sound_and_recover_after(self):
        """Real FFmpeg mix must reduce beat level during microphone activity."""
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            source = work / "voice.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=15:duration=3",
                "-f", "lavfi", "-i",
                "sine=frequency=900:sample_rate=48000:duration=1",
                "-c:v", "mpeg4", "-q:v", "6", "-c:a", "aac", str(source),
            ], check=True, capture_output=True)

            def tone_beat(theme, destination, music_profile=None):
                subprocess.run([
                    "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=22050:duration=3",
                    "-c:a", "pcm_s16le", str(destination)
                ], check=True, capture_output=True)
                return {"title": "Measurement Tone", "bpm": 120,
                        "origin": "original_generated"}

            with patch("soundtrack.create_original_beat", side_effect=tone_beat):
                result = add_soundtrack(source, "fitness", sound_mode="low")
            self.assertTrue(result["dynamic_source_ducking"])
            self.assertEqual(result["original_audio_volume"], 0.2)
            decoded = subprocess.check_output([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                "-i", str(source), "-vn", "-ac", "1", "-ar", "48000",
                "-f", "f32le", "pipe:1"])
            pcm = array.array("f")
            pcm.frombytes(decoded)
            rate = 48000

            def tone_strength(start: float, end: float) -> float:
                section = pcm[round(start * rate):round(end * rate)]
                cos = sum(sample * math.cos(2 * math.pi * 440 * i / rate)
                          for i, sample in enumerate(section))
                sin = sum(sample * math.sin(2 * math.pi * 440 * i / rate)
                          for i, sample in enumerate(section))
                return 2 * math.hypot(cos, sin) / len(section)

            under_microphone = tone_strength(0.4, 0.8)
            after_microphone = tone_strength(1.5, 1.9)
            self.assertGreater(after_microphone, 0.02)
            self.assertLess(under_microphone, after_microphone * 0.75)
            self.assertAlmostEqual(probe_media(source)["duration"], 3, delta=0.15)

    def test_silent_video_can_receive_original_music(self):
        """A video with no audio stream still exports a valid soundtrack."""
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "silent.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=15:duration=2.1",
                "-c:v", "mpeg4", "-q:v", "6", str(source)
            ], check=True, capture_output=True)
            self.assertFalse(probe_media(source)["has_audio"])
            result = add_soundtrack(source, "fitness", sound_mode="low")
            self.assertFalse(result["dynamic_source_ducking"])
            self.assertEqual(result["original_audio_volume"], 0)
            info = probe_media(source)
            self.assertTrue(info["has_audio"])
            self.assertAlmostEqual(info["duration"], 2.1, delta=0.15)
            self.assertFalse(list(Path(root).glob("*.partial.mp4")))

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
