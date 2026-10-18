"""Exercise multi-source FFmpeg montage and theme-aware non-destructive exports."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from montage import (
    FILTER_PRESETS, MAX_SOURCES, allocation, apply_filter,
    edit_many, filter_catalog,
)


class AllocationTests(unittest.TestCase):
    def test_represents_every_video_and_respects_budget(self):
        plan = allocation([8, 2000, 20], 30)
        self.assertEqual(len(plan), 3)
        self.assertTrue(all(x >= 1 for x in plan))
        self.assertAlmostEqual(sum(plan), 30, places=2)
        self.assertLessEqual(plan[0], 8)
        self.assertGreater(plan[1], plan[0])

    def test_short_sources_are_never_overallocated(self):
        plan = allocation([1.5, 2.5, 20], 45)
        self.assertAlmostEqual(sum(plan), 24)
        self.assertEqual(plan[:2], [1.5, 2.5])
        self.assertEqual(plan[2], 20)

    def test_bad_inputs_rejected(self):
        with self.assertRaises(ValueError):
            allocation([0.5, 20], 30)
        with self.assertRaises(ValueError):
            allocation([4] * (MAX_SOURCES + 1), 45)
        with self.assertRaises(ValueError):
            allocation([10], 181)

    def test_recommendations_are_curated_and_whitelisted(self):
        for theme in ("fitness", "motivation", "sport", "lifestyle", "auto"):
            catalog = filter_catalog(theme)
            self.assertEqual(catalog[0]["id"], "original")
            self.assertTrue(any(x["recommended"] for x in catalog))
            self.assertEqual(set(x["id"] for x in catalog), set(FILTER_PRESETS))
            self.assertTrue(all(x["css"] for x in catalog))
        fitness = filter_catalog("fitness")
        self.assertIn("impact", [x["id"] for x in fitness if x["recommended"]])
        self.assertNotIn("soleil", [x["id"] for x in fitness if x["recommended"]])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg absent")
class MultiRenderTests(unittest.TestCase):
    @staticmethod
    def create_clip(path: Path, color: str, with_audio: bool) -> None:
        command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                   "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=15"]
        if with_audio:
            command += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
        command += ["-t", "3.4", "-c:v", "mpeg4", "-q:v", "4"]
        if with_audio:
            command += ["-c:a", "aac"]
        command += ["-y", str(path)]
        subprocess.run(command, check=True, capture_output=True)

    @staticmethod
    def dimensions(path: Path) -> str:
        return subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0",
            str(path)], text=True).strip()

    def test_merge_two_mobile_rushes_into_one_export_with_mixed_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "first.mp4", root / "second.mp4"
            self.create_clip(first, "red", True)
            self.create_clip(second, "blue", False)
            original = root / "joined.mp4"
            meta = edit_many(
                [first, second], original,
                theme="fitness", aspect="vertical", target_seconds=10,
                source_names=["gym-morning.mp4", "gym-night.mp4"],
                transcribe=False, size=360)
            self.assertTrue(original.is_file())
            self.assertGreater(original.stat().st_size, 2000)
            self.assertEqual(self.dimensions(original), "360,640")
            self.assertEqual(meta["source_count"], 2)
            self.assertEqual(len(meta["sources"]), 2)
            self.assertEqual([x["source_index"] for x in meta["clips"] if "source_index" in x],
                             sorted(x["source_index"] for x in meta["clips"]))
            self.assertGreater(meta["rendered_duration_seconds"], 4.0)
            self.assertLessEqual(meta["rendered_duration_seconds"], 7.0)
            self.assertNotIn("squat", meta["hashtags"])
            self.assertEqual(meta["sources"][1]["name"], "gym-night.mp4")
            # No-audio rush must still be muxed with AAC for normalized concat.
            stream = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_name", "-of", "csv=p=0",
                str(original)], text=True).strip()
            self.assertEqual(stream, "aac")
            before = original.read_bytes()
            filtered = root / "filters" / "impact.mp4"
            apply_filter(original, filtered, "impact")
            self.assertTrue(filtered.is_file())
            self.assertGreater(filtered.stat().st_size, 1000)
            self.assertEqual(self.dimensions(filtered), "360,640")
            self.assertEqual(original.read_bytes(), before)
            self.assertNotEqual(filtered.read_bytes(), before)
            with self.assertRaises(ValueError):
                apply_filter(original, root / "bad.mp4", "not-a-filter")

    def test_every_theme_filter_encodes_correctly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "short.mp4"
            self.create_clip(source, "orange", True)
            for preset in FILTER_PRESETS:
                if preset == "original":
                    continue
                with self.subTest(preset=preset):
                    destination = root / f"{preset}.mp4"
                    apply_filter(source, destination, preset)
                    self.assertTrue(destination.exists())
                    self.assertGreater(destination.stat().st_size, 500)
                    self.assertEqual(self.dimensions(destination), "160,90")

    def test_horizontal_multi_rush_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "a.mp4", root / "b.mp4"
            self.create_clip(first, "green", False)
            self.create_clip(second, "yellow", False)
            result = root / "horizontal.mp4"
            meta = edit_many([first, second], result, aspect="youtube",
                             target_seconds=10, size=360, transcribe=False)
            self.assertEqual(self.dimensions(result), "640,360")
            self.assertEqual(meta["resolution"], "16:9")
            self.assertEqual(meta["source_count"], 2)
            self.assertTrue(result.stat().st_size > 1000)


if __name__ == "__main__":
    unittest.main()
