import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from editor import Clip, render


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg absent")
class RenderingRobustnessTests(unittest.TestCase):
    def test_burned_captions_and_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            source = home / "raw.mp4"
            output = home / "video.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=15",
                            "-f", "lavfi", "-i", "sine=frequency=300",
                            "-t", "4", "-c:v", "mpeg4", "-c:a", "aac", str(source)], check=True)
            segment = {"start": .5, "end": 3.0, "text": "Chaque repetition compte vraiment"}
            metadata = {}
            render(source, output, [Clip(0, 4, 1)], metadata, [segment],
                   vertical=True, has_audio=True, size=360)
            self.assertGreater(output.stat().st_size, 1000)
            captions = (home / "segments" / "0000.ass").read_text()
            self.assertIn("CHAQUE REPETITION", captions)
            self.assertGreater(metadata["rendered_duration_seconds"], 0)


    def test_early_audio_eof_does_not_cut_off_picture(self):
        """A damaged/short mobile audio track must never decide clip length."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            source, output = home / "short-audio.mp4", home / "edited.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i",
                "testsrc2=size=160x90:rate=15:duration=3.4",
                "-f", "lavfi", "-i",
                "sine=frequency=500:sample_rate=48000:duration=0.65",
                "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", str(source),
            ], check=True, capture_output=True)
            # Verify this fixture really has a microphone track ending early.
            video_length = float(subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=duration", "-of", "default=nk=1:nw=1",
                str(source)], text=True))
            audio_length = float(subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=duration", "-of", "default=nk=1:nw=1",
                str(source)], text=True))
            self.assertGreater(video_length - audio_length, 2.0)

            render(source, output, [Clip(0, 3, 1)], {}, [],
                   vertical=True, has_audio=True, size=360)
            output_video = float(subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=duration", "-of", "default=nk=1:nw=1",
                str(output)], text=True))
            output_audio = float(subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=duration", "-of", "default=nk=1:nw=1",
                str(output)], text=True))
            self.assertGreater(output_video, 2.85)
            self.assertGreater(output_audio, 2.85)
            self.assertLess(output_video, 3.2)

    def test_audio_longer_than_video_does_not_extend_montage_timeline(self):
        """Audio should not make the editor select non-existent video frames."""
        from editor import probe_media

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "long-microphone.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=15:duration=2.4",
                "-f", "lavfi", "-i", "sine=frequency=500:duration=3.8",
                "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", str(source)
            ], check=True, capture_output=True)
            info = probe_media(source)
            self.assertTrue(info["has_audio"])
            self.assertAlmostEqual(info["duration"], 2.4, delta=0.12)

    def test_video_without_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            source = home / "silent.mp4"
            output = home / "video.mp4"
            subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                            "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=15",
                            "-t", "3", "-c:v", "mpeg4", str(source)], check=True)
            render(source, output, [Clip(0, 3, 1)], {}, [], False, False, 360)
            info = subprocess.check_output(
                ["ffprobe", "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                 str(output)], text=True)
            self.assertIn("aac", info)
