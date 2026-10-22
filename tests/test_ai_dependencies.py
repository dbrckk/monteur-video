"""Prevent the PyAV 18/19 metadata_errors regression in optional subtitles."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class OptionalWhisperCompatibilityTests(unittest.TestCase):
    def test_old_faster_whisper_receives_compatible_pyav(self):
        dependencies = (ROOT / "requirements-ai.txt").read_text()
        self.assertIn("faster-whisper", dependencies)
        self.assertIn("av>=17.1,<18", dependencies)

    def test_production_ai_image_runs_actual_audio_decode_and_transcribe(self):
        workflow = (ROOT / ".github" / "workflows" /
                    "docker-smoke.yml").read_text()
        self.assertIn("from faster_whisper.audio import decode_audio", workflow)
        self.assertIn("model.transcribe(", workflow)
        self.assertIn("list(segments)", workflow)
        self.assertIn("av.__version__", workflow)


if __name__ == "__main__":
    unittest.main()
