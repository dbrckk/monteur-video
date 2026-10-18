"""Music identity and tempo follow the video, not merely its selected theme."""
import tempfile
import unittest
import wave
from pathlib import Path

from soundtrack import create_original_beat, select_music_profile
from visual_quality import VisualSample


class MatchMusicTests(unittest.TestCase):
    @staticmethod
    def samples(motion, detail=23, brightness=110):
        return [VisualSample(i * .5, brightness, motion, detail) for i in range(24)]

    def test_fitness_motion_sets_different_music_at_same_theme(self):
        easy = select_music_profile("fitness", self.samples(.7), scene_count=1, source_seconds=60)
        workout = select_music_profile("fitness", self.samples(7), scene_count=7, source_seconds=60)
        intense = select_music_profile("fitness", self.samples(16), scene_count=18, source_seconds=60)
        self.assertEqual([easy["energy"], workout["energy"], intense["energy"]],
                         ["low", "medium", "high"])
        self.assertLess(easy["bpm"], workout["bpm"])
        self.assertLess(workout["bpm"], intense["bpm"])
        self.assertNotEqual(easy["title"], intense["title"])
        self.assertEqual(intense["selection_method"], "visual_motion_scene_density")

    def test_unknown_or_black_frames_fall_back_to_theme(self):
        empty = select_music_profile("sport", [], scene_count=42, source_seconds=120)
        blank = select_music_profile("sport", self.samples(10, detail=0, brightness=4))
        self.assertEqual(empty["selection_method"], "theme_fallback")
        self.assertEqual(blank["selection_method"], "theme_fallback")
        self.assertEqual(empty["bpm"], blank["bpm"])

    def test_reordered_rushes_choose_same_track(self):
        files = [self.samples(13), self.samples(1), self.samples(6)]
        one = select_music_profile("sport", [x for rush in files for x in rush],
                                   scene_count=14, source_seconds=100)
        two = select_music_profile("sport", [x for rush in reversed(files) for x in rush],
                                   scene_count=14, source_seconds=100)
        self.assertEqual(one, two)

    def test_audio_generation_uses_selected_bpm_and_title(self):
        profile = select_music_profile("fitness", self.samples(17),
                                       scene_count=30, source_seconds=60)
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "matched.wav"
            metadata = create_original_beat("fitness", file, bars=2,
                                            music_profile=profile)
            self.assertEqual(metadata["bpm"], profile["bpm"])
            self.assertEqual(metadata["title"], profile["title"])
            self.assertEqual(metadata["energy"], "high")
            with wave.open(str(file)) as reader:
                expected = 8 * 60 / profile["bpm"]
                self.assertAlmostEqual(reader.getnframes() / reader.getframerate(),
                                       expected, delta=.003)


if __name__ == "__main__":
    unittest.main()
