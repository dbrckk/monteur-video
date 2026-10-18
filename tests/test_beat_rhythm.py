"""High-energy sports edits must use a consistent musical beat grid."""
import unittest

from editor import plan_clips
from soundtrack import beat_duration


class BeatAwareCutTests(unittest.TestCase):
    def test_sport_highlights_shorter_than_slow_generic_edit(self):
        tempo = beat_duration("fitness")
        fast = plan_clips(70, [], [], [], target_seconds=15, beat_seconds=tempo)
        slow = plan_clips(70, [], [], [], target_seconds=15)
        self.assertTrue(fast)
        self.assertTrue(slow)
        self.assertLessEqual(max(x.duration for x in fast), 8 * tempo + 0.02)
        self.assertGreater(max(x.duration for x in slow),
                           max(x.duration for x in fast))

    def test_short_clip_lengths_fit_beat_measures(self):
        tempo = beat_duration("sport")
        clips = plan_clips(80, [], [], [], target_seconds=15, beat_seconds=tempo)
        durations = [c.duration for c in clips]
        self.assertGreaterEqual(len(durations), 4)
        self.assertTrue(all(1.0 <= d <= 8 * tempo + .03 for d in durations))
        self.assertLessEqual(sum(durations), 15.02)
        for duration in durations[:-1]:
            self.assertLess(abs(duration / (4 * tempo) -
                                round(duration / (4 * tempo))), 0.10)

    def test_no_overlapping_cuts(self):
        tempo = beat_duration("fitness")
        clips = plan_clips(35, [2, 5, 7, 13, 22, 28], [], [], 15,
                           beat_seconds=tempo)
        self.assertTrue(all(c.end <= nxt.start + 0.01
                            for c, nxt in zip(clips, clips[1:])))
        self.assertTrue(all(x.duration >= 1 for x in clips))


if __name__ == "__main__":
    unittest.main()
