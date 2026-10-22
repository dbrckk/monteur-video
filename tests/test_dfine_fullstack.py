"""Offline safety checks for the non-production detector full-stack benchmark."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.benchmark_dfine_fullstack import (
    CGROUP_LIMIT_MIB, QUALIFICATION_PEAK_MIB,
    MODEL_SHA256, MODEL_REVISION, EXPECTED_OUTPUT_SHAPES,
)


PROJECT = Path(__file__).resolve().parents[1]


class DfineFullstackSafetyTests(unittest.TestCase):
    def test_immutable_model_identity_and_headroom(self):
        self.assertEqual(len(MODEL_SHA256), 64)
        self.assertEqual(len(MODEL_REVISION), 40)
        self.assertEqual(CGROUP_LIMIT_MIB, 512)
        self.assertLessEqual(QUALIFICATION_PEAK_MIB, 420)
        self.assertEqual(EXPECTED_OUTPUT_SHAPES,
                         ((1, 300, 366), (1, 300, 4)))

    def test_default_production_dockerfile_contains_no_research_detector(self):
        production = (PROJECT / "Dockerfile").read_text(encoding="utf-8")
        self.assertNotIn("dfine", production.lower())
        self.assertNotIn("onnxruntime", production.lower())
        self.assertNotIn("benchmark_dfine", production.lower())

    def test_research_benchmark_is_not_imported_by_public_video_engine(self):
        for path in ("server.py", "editor.py", "pose_reframe.py",
                     "montage.py", "shot_composition.py"):
            with self.subTest(path=path):
                content = (PROJECT / path).read_text(encoding="utf-8").lower()
                self.assertNotIn("benchmark_dfine_fullstack", content)
                self.assertNotIn("dfine", content)

    def test_results_explicitly_withhold_commercial_deployment(self):
        doc = json.loads((PROJECT / "docs" /
                           "gym-detector-benchmark-results.json").read_text())
        self.assertFalse(doc["fp32"]["production_qualified"])
        self.assertIn("HOLD", doc["release_decision"])

    def test_workflow_not_copied_into_render(self):
        source = (PROJECT / "scripts" / "Dockerfile.dfine-fullstack").read_text()
        self.assertIn("FROM monteur-v1:fullstack-base", source)
        self.assertIn("USER appuser", source)
        self.assertIn("benchmark_dfine_fullstack.py", source)
        ci = (PROJECT / ".github" / "workflows" /
              "gym-detector-fullstack.yml").read_text()
        self.assertIn("--memory=512m", ci)
        self.assertIn("--cpus=0.10", ci)
        self.assertIn("Objects365 academic-only", ci)


if __name__ == "__main__":
    unittest.main()
