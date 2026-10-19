import unittest
from dataclasses import dataclass
from action_story import action_phases, candidate_action_score, narrative_signals, speech_exercise, timeline_phases, narrative_coverage
from editor import plan_clips


@dataclass
class S:
    time: float
    motion: float
    luminance: float = 110
    detail: float = 20


class ActionUnderstandingTests(unittest.TestCase):
    def test_explicit_transcript_only_no_visual_exercise_hallucinations(self):
        self.assertEqual(speech_exercise([])["exercise"], None)
        s = speech_exercise([{"text":"Je fais du développé couché maintenant."}])
        self.assertEqual(s["exercise"], "developpe_couche")
        self.assertEqual(s["source"], "transcript_explicit")
        ambiguous = speech_exercise([{"text":"Squat puis traction"}])
        self.assertIsNone(ambiguous["exercise"])

    def test_detects_contiguous_burst_not_gaps(self):
        seq = [S(i*.5, 1 if i < 6 or i >= 13 else 12) for i in range(24)]
        result = action_phases(seq, 12)
        self.assertEqual(len(result), 1)
        self.assertGreater(result[0]["start"], 2)
        self.assertGreater(result[0]["end"], result[0]["start"])
        self.assertGreater(candidate_action_score(3, 7, result), 1)
        self.assertEqual(candidate_action_score(0, 2, result), 0)

    def test_sparse_sampling_never_bridges_unknown_time(self):
        seq = [S(i*.5, 1) for i in range(6)]
        seq += [S(40+i*.5, 12) for i in range(4)]
        seq += [S(95+i*.5, 12) for i in range(4)]
        phases = action_phases(seq, 110)
        self.assertEqual(len(phases), 2)
        self.assertTrue(all(x["end"]-x["start"] < 4 for x in phases))

    def test_motion_phase_score_promotes_action_clip(self):
        phases = [{"start": 5.5, "end": 9.0}]
        self.assertGreater(candidate_action_score(5, 9, phases),
                           candidate_action_score(0, 4, phases))
        signal = narrative_signals([S(i*.5, 2) for i in range(16)], [], 8)
        self.assertFalse(signal["actual_pose_or_repetition_recognition"])
        self.assertIsNone(signal["exercise"])

    def test_action_phase_timeline_and_coverage_are_grounded(self):
        seq = [S(i*.5, 1 if i < 6 or i >= 13 else 12) for i in range(24)]
        story = narrative_signals(seq, [], 12)
        phases = story["timeline_phases"]
        self.assertEqual([p["phase"] for p in phases],
                         ["before_observed_effort", "observed_effort",
                          "after_observed_effort"])
        self.assertTrue(all(p["end"] > p["start"] for p in phases))
        self.assertTrue(all(p["evidence"] != "pose_recognition" for p in phases))
        from editor import Clip
        coverage = narrative_coverage([Clip(3, 7, 1)], phases)
        self.assertGreater(coverage["observed_effort_ratio"], 0.5)
        self.assertLessEqual(coverage["observed_effort_ratio"], 1.0)

    def test_no_evidence_means_no_phase_invention(self):
        self.assertEqual(timeline_phases([], 20), [])
        self.assertEqual(narrative_coverage([], [])["observed_effort_ratio"], 0)

    def test_plan_clips_still_respects_chronological_order(self):
        clips = plan_clips(12, [], [], [], target_seconds=5, allow_short=True,
                           action_bouts=[{"start":6, "end":10}])
        self.assertTrue(all(a.start <= b.start for a,b in zip(clips,clips[1:])))


if __name__ == "__main__":
    unittest.main()
