import unittest
from dataclasses import dataclass
from action_story import action_phases, candidate_action_score, narrative_signals, speech_exercise, timeline_phases, narrative_coverage, motion_cadence, candidate_cadence_score, short_complete_action_intervals, completed_action_coverage
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

    def test_periodic_visual_motion_without_fabricated_repetition_count(self):
        seq = [S(i * .5, 14 if i % 4 == 2 else 5) for i in range(38)]
        found = motion_cadence(seq, [{"start": 0.0, "end": 19.0}])
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["visual_cycle_seconds"], 2.0, places=1)
        self.assertTrue(found[0]["not_exercise_rep_count"])
        self.assertNotIn("repetitions", found[0])
        self.assertLessEqual(found[0]["confidence"], 0.65)

    def test_cadence_rejects_sparse_and_unconvincing_motion(self):
        flat = [S(i * .5, 8) for i in range(30)]
        self.assertEqual(motion_cadence(flat, [{"start": 0, "end": 15}]), [])
        discontinuous = [S(i * 2.0, 14 if i % 2 else 4) for i in range(12)]
        self.assertEqual(motion_cadence(discontinuous, [{"start": 0, "end": 24}]), [])

    def test_cadence_bonus_only_for_confident_overlap(self):
        cadence = [{"start": 4, "end": 10, "confidence": .65,
                    "kind": "possible_periodic_visual_motion"}]
        self.assertGreater(candidate_cadence_score(5, 9, cadence), 0)
        self.assertEqual(candidate_cadence_score(0, 3, cadence), 0)
        self.assertEqual(candidate_cadence_score(0, 6, cadence), 0)
        self.assertLessEqual(candidate_cadence_score(5, 9, cadence), .8)

    def test_editor_uses_cadence_without_reordering_clips(self):
        seq = [S(i * .5, 5) for i in range(24)]
        cadence = [{"start": 6, "end": 10, "confidence": .65,
                    "kind": "possible_periodic_visual_motion"}]
        baseline = plan_clips(12, [], [], [], target_seconds=5,
                              allow_short=True, visual_samples=seq)
        improved = plan_clips(12, [], [], [], target_seconds=5,
                              allow_short=True, visual_samples=seq,
                              motion_cadence=cadence)
        self.assertTrue(all(a.start <= b.start for a,b in zip(improved, improved[1:])))
        self.assertTrue(improved)
        self.assertGreaterEqual(max(c.score for c in improved),
                                max(c.score for c in baseline))

    def test_short_action_kept_whole_instead_of_mid_motion_cut(self):
        from editor import Clip
        bout = {"start": 4.0, "end": 6.5, "confidence": .76,
                "kind": "observed_motion_bout"}
        seq = [S(i * .5, 5) for i in range(28)]
        clips = plan_clips(14, [], [], [], 5, allow_short=True,
                           visual_samples=seq, beat_seconds=.5, action_bouts=[bout])
        self.assertTrue(any(c.preserves_action for c in clips))
        self.assertTrue(any(c.start <= 4.0 and c.end >= 6.5 for c in clips))
        self.assertLessEqual(sum(c.duration for c in clips), 5.001)
        self.assertEqual(clips, sorted(clips, key=lambda c: c.start))
        self.assertEqual(completed_action_coverage(clips, [bout])["whole_bouts_in_export"], 1)

    def test_protected_action_is_never_partially_trimmed_for_short_budget(self):
        bout = {"start": 4.0, "end": 6.5, "confidence": .76,
                "kind": "observed_motion_bout"}
        seq = [S(i * .5, 5) for i in range(28)]
        clips = plan_clips(14, [], [], [], 2, allow_short=True,
                           visual_samples=seq, beat_seconds=.5, action_bouts=[bout])
        self.assertTrue(clips)
        self.assertFalse(any(c.preserves_action for c in clips))
        self.assertLessEqual(sum(c.duration for c in clips), 2.001)

    def test_protection_never_crosses_a_real_scene_cut_or_unknown_gap(self):
        bout = {"start": 4.0, "end": 6.5, "confidence": .76,
                "kind": "observed_motion_bout"}
        self.assertEqual(short_complete_action_intervals([bout],
                          [(0, 12)], [5.0], 4.0), [])
        self.assertEqual(short_complete_action_intervals([bout],
                          [(0, 4.5), (5.0, 12)], [], 4.0), [])
        self.assertEqual(short_complete_action_intervals(
                          [{**bout, "end": 10}], [(0, 12)], [], 4), [])

    def test_only_measured_motion_is_counted_as_complete(self):
        from editor import Clip
        bout = {"start": 4.0, "end": 6.5, "confidence": .76,
                "kind": "observed_motion_bout"}
        partial = completed_action_coverage([Clip(4.5, 6, 3)], [bout])
        self.assertEqual(partial["observed_motion_bouts"], 1)
        self.assertEqual(partial["whole_bouts_in_export"], 0)
        self.assertTrue(partial["not_exercise_repetition_count"])
        self.assertIsNone(completed_action_coverage([], [])["whole_bout_ratio"])

    def test_plan_clips_still_respects_chronological_order(self):
        clips = plan_clips(12, [], [], [], target_seconds=5, allow_short=True,
                           action_bouts=[{"start":6, "end":10}])
        self.assertTrue(all(a.start <= b.start for a,b in zip(clips,clips[1:])))


if __name__ == "__main__":
    unittest.main()
