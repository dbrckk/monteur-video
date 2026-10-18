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
