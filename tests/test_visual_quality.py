"""Visual quality heuristics: never pick black footage over useful silent action."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from editor import plan_clips
from visual_quality import VisualSample, analyze_visual, clip_quality, usable_ranges


class VisualScoringTests(unittest.TestCase):
    def test_rejects_black_and_frozen_frames(self):
        frames = [VisualSample(i * 0.5, 16, 0, 0) for i in range(10)]
        score, rejected = clip_quality(frames, 0, 5)
        self.assertTrue(rejected)
        self.assertLess(score, -4)
        self.assertEqual(usable_ranges(frames, 5), [])

    def test_three_second_frozen_frame_is_not_selected(self):
        frozen = [VisualSample(i * 0.5, 125, 0, 32) for i in range(12)]
        moving = [VisualSample(6 + i * 0.5, 125, 8, 32) for i in range(6)]
        self.assertEqual(usable_ranges(frozen + moving, 9), [(6.0, 9)])

    def test_rewards_movement_and_fine_detail(self):
        sharp = [VisualSample(i * 0.5, 120, 9, 33) for i in range(10)]
        blurred = [VisualSample(i * 0.5, 120, 5, 10) for i in range(10)]
        self.assertGreater(clip_quality(sharp, 0, 5)[0],
                           clip_quality(blurred, 0, 5)[0])
        self.assertFalse(clip_quality(blurred, 0, 5)[1])

    def test_all_bad_frames_fallback_stays_within_target(self):
        frozen = [VisualSample(i * 0.5, 16, 0, 0) for i in range(90)]
        clips = plan_clips(45, [], [], [], 10, visual_samples=frozen)
        self.assertAlmostEqual(sum(x.duration for x in clips), 10, places=2)

    def test_silent_workout_survives_unavailable_visual_analysis(self):
        clips = plan_clips(30, [], [(0, 29)], [], 10, visual_samples=[])
        self.assertTrue(clips)
        self.assertLessEqual(sum(c.duration for c in clips), 10.01)
        self.assertGreater(sum(c.duration for c in clips), 5)
        # No motion analysis must not restrict selection to the last second.
        self.assertTrue(any(c.start < 20 for c in clips))

    def test_selects_silent_action_not_black_opener(self):
        samples = [VisualSample(i * 0.5, 16 if i < 6 else 120,
                                0 if i < 6 else 9,
                                0 if i < 6 else 33) for i in range(18)]
        self.assertEqual(usable_ranges(samples, 9), [(3.0, 9)])
        clips = plan_clips(9, [], [(0, 9)], [], 5,
                           allow_short=True, visual_samples=samples)
        self.assertTrue(clips)
        self.assertGreaterEqual(clips[0].start, 3)
        self.assertLessEqual(sum(x.duration for x in clips), 5.01)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg absent")
class VisualFFmpegTests(unittest.TestCase):
    def test_real_black_movement_and_blurred_video(self):
        with tempfile.TemporaryDirectory() as temporary:
            media = Path(temporary) / "quality.mp4"
            command = [
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x180:r=10:d=3",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=3",
                "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=10:duration=3",
                "-filter_complex",
                "[2:v]gblur=sigma=12[blur];[0:v][1:v][blur]concat=n=3:v=1:a=0[out]",
                "-map", "[out]", "-c:v", "mpeg4", "-q:v", "4", str(media),
            ]
            subprocess.run(command, check=True, capture_output=True)
            samples = analyze_visual(media)
            self.assertGreaterEqual(len(samples), 15)
            black_score, black_rejected = clip_quality(samples, 0, 3)
            motion_score, motion_rejected = clip_quality(samples, 3, 6)
            blur_score, _ = clip_quality(samples, 6.5, 9)
            self.assertTrue(black_rejected)
            self.assertFalse(motion_rejected)
            self.assertGreater(motion_score, blur_score)
            self.assertGreater(motion_score, black_score)
            usable = usable_ranges(samples, 9)
            self.assertTrue(usable)
            self.assertGreaterEqual(usable[0][0], 2.5)


if __name__ == "__main__":
    unittest.main()
