"""Actual FFmpeg regressions for atomic outputs and bounded temporary storage."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from editor import Clip, execute, render


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"),
                     "Real FFmpeg/FFprobe required")
class AtomicRenderingTests(unittest.TestCase):
    @staticmethod
    def fixture(path):
        subprocess.run([
            "ffmpeg", "-y", "-nostdin", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            "testsrc2=size=160x90:rate=15:duration=3.3",
            "-c:v", "mpeg4", "-q:v", "4", str(path),
        ], check=True, capture_output=True)

    @staticmethod
    def verify_video(path, dimensions="640,360"):
        result = subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0",
            str(path)], text=True).strip()
        if result != dimensions:
            raise AssertionError((result, dimensions))
        return path.stat().st_size

    def test_real_three_segment_render_emits_only_valid_output(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            original, target = root / "input.mp4", root / "final.mp4"
            self.fixture(original)
            metadata = {}
            render(original, target, [Clip(0, 1.0, 1), Clip(1.0, 2.0, 1),
                                     Clip(2.0, 3.0, 1)], metadata, [],
                   vertical=False, has_audio=False, size=360)
            self.assertGreater(self.verify_video(target), 5000)
            self.assertAlmostEqual(metadata["rendered_duration_seconds"], 3)
            self.assertEqual(len(list(root.glob(".final-segments-*"))), 0)
            self.assertFalse((root / "segments").exists())
            self.assertFalse((root / "assembled.mp4").exists())

    def test_old_successful_mp4_survives_concat_error(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            original, target = root / "input.mp4", root / "final.mp4"
            self.fixture(original)
            render(original, target, [Clip(0, 1.2, 1)], {}, [],
                   vertical=False, has_audio=False, size=360)
            initial = sha256(target.read_bytes()).hexdigest()

            def broken_concat(args, timeout=None):
                if "-f" in args and "concat" in args:
                    raise RuntimeError("Simulated FFmpeg disk error")
                return execute(args, timeout)

            with patch("editor.execute", side_effect=broken_concat):
                with self.assertRaisesRegex(RuntimeError, "Simulated"):
                    render(original, target, [Clip(0, 1.2, 1)], {}, [],
                           vertical=False, has_audio=False, size=360)
            self.assertEqual(sha256(target.read_bytes()).hexdigest(), initial)
            self.assertEqual(list(root.glob(".final-segments-*")), [])

    def test_corrupted_staged_output_not_published(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            original, target = root / "input.mp4", root / "final.mp4"
            self.fixture(original)
            render(original, target, [Clip(0, 1.0, 1)], {}, [],
                   vertical=False, has_audio=False, size=360)
            initial = sha256(target.read_bytes()).hexdigest()
            # Corrupted dimensions are rejected even if FFmpeg exits 0.
            with patch("editor.probe_media", return_value={
                "width": 100, "height": 100, "has_audio": True, "duration": 1.0
            }):
                with self.assertRaisesRegex(RuntimeError, "MP4 final invalide"):
                    render(original, target, [Clip(1.0, 2.0, 1)], {}, [],
                           vertical=False, has_audio=False, size=360)
            self.assertEqual(sha256(target.read_bytes()).hexdigest(), initial)
            self.assertEqual(list(root.glob(".final-segments-*")), [])

    def test_two_simultaneous_exports_cannot_share_temporary_segments(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            original = root / "input.mp4"
            self.fixture(original)

            def job(name):
                output = root / f"{name}.mp4"
                render(original, output, [Clip(0.0, 1.1, 1)], {}, [],
                       vertical=False, has_audio=False, size=360)
                return self.verify_video(output)

            with ThreadPoolExecutor(max_workers=2) as jobs:
                sizes = list(jobs.map(job, ("first", "second")))
            self.assertTrue(all(n > 3000 for n in sizes))
            self.assertEqual(list(root.glob(".*-segments-*")), [])


if __name__ == "__main__":
    unittest.main()
