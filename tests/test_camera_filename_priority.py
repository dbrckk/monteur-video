"""Regression tests for true Android filename chronology over inert camera tags."""
import tempfile
import unittest
from pathlib import Path

from montage import chronological_order


class AndroidCameraChronologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.sources = [Path(self.temp.name) / f"upload-{i}.mp4" for i in range(3)]
        for i, path in enumerate(self.sources):
            path.write_bytes(bytes([11 + i]) * 200)
        self.names = ["VID_20261023_154200.mp4",
                      "PXL_20261023_150010.mp4",
                      "VID_20261023_153001.mp4"]
        self.samples = [[], [], []]

    def order(self, info, names=None, permutation=None):
        p = permutation or [0, 1, 2]
        paths = [self.sources[i] for i in p]
        samples = [self.samples[i] for i in p]
        meta = [info[i] for i in p]
        filename = [self.names[i] for i in p] if names is None else [names[i] for i in p]
        order, method = chronological_order(paths, samples, meta, filename)
        return [p[i] for i in order], method

    def test_single_utc_tag_does_not_block_complete_camera_filenames(self):
        info = [{"captured_at": None},
                {"captured_at": "2026-10-23T13:00:10+00:00"},
                {"captured_at": None}]
        self.assertEqual(self.order(info), ([1, 2, 0], "camera_filename_time"))
        self.assertEqual(self.order(info, permutation=[2, 0, 1]),
                         ([1, 2, 0], "camera_filename_time"))

    def test_identical_creation_tags_do_not_override_native_capture_names(self):
        info = [{"captured_at": "2026-10-24T00:00:00+00:00"}] * 3
        self.assertEqual(self.order(info), ([1, 2, 0], "camera_filename_time"))

    def test_distinct_utc_tags_take_precedence_over_local_filename_clock(self):
        info = [{"captured_at": "2026-10-23T09:00:00+00:00"},
                {"captured_at": "2026-10-23T11:00:00+00:00"},
                {"captured_at": "2026-10-23T10:00:00+00:00"}]
        self.assertEqual(self.order(info), ([0, 2, 1], "capture_time"))

    def test_missing_filename_does_not_invent_mixed_clock_chronology(self):
        info = [{"captured_at": None},
                {"captured_at": "2026-10-23T13:00:10+00:00"},
                {"captured_at": None}]
        names = self.names.copy()
        names[0] = "sent-from-android.mp4"
        indices, method = self.order(info, names=names)
        self.assertEqual(sorted(indices), [0, 1, 2])
        self.assertEqual(method, "visual_continuity_no_reliable_timestamps")

    def test_two_distinct_camera_tags_keep_anchors_even_when_names_disagree(self):
        info = [{"captured_at": "2026-10-23T12:00:00+00:00"},
                {"captured_at": None},
                {"captured_at": "2026-10-23T11:00:00+00:00"}]
        indices, method = self.order(info)
        self.assertEqual(method, "capture_anchors_visual_gaps")
        self.assertLess(indices.index(2), indices.index(0))


if __name__ == "__main__":
    unittest.main()
