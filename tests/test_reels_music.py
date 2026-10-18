"""Discover real Reels sounds for a matching workout without downloading music."""
import unittest
from unittest.mock import patch

import reels_music


class ChartParserTests(unittest.TestCase):
    CHART = '''
      <a href="/sound/calm-track/">
        <img alt="Calm Motion — Artist One" />
      </a>
      <a href="/sound/fein-track/">
        <img alt="FE!N — Artist Two" />
      </a>
      <a href="/sound/instrumental-track/">
        <img alt="POWER (Instrumental) — Artist Three" />
      </a>
      <a href="/sound/fein-track/">
        <img alt="FE!N — Artist Two" />
      </a>
      <a href="https://evil.example/sound/untrusted/">
        <img alt="Injected — Nobody" />
      </a>
    '''

    def tearDown(self):
        reels_music._chart_cached.cache_clear()

    def test_parses_public_chart_deduplicates_and_restricts_domains(self):
        tracks = reels_music.parse_chart(self.CHART)
        self.assertEqual(len(tracks), 3)
        self.assertEqual(tracks[0]["title"], "Calm Motion")
        self.assertEqual(tracks[1]["artist"], "Artist Two")
        self.assertEqual(tracks[2]["vocals"], "instrumental")
        self.assertTrue(all(t["source_url"].startswith(reels_music.SOURCE + "/sound/")
                            for t in tracks))

    def test_live_chart_selects_matching_high_energy_audio(self):
        def fetch(url):
            if "/sound/fein-track/" in url:
                return '<a href="https://www.instagram.com/reels/audio/123456789/"></a>'
            if "/sound/instrumental-track/" in url:
                return '<a href="https://www.instagram.com/reels/audio/987654321/"></a>'
            if "/sound/calm-track/" in url:
                return '<a href="https://www.instagram.com/reels/audio/111111111/"></a>'
            return self.CHART

        with patch.object(reels_music, "_fetch_public_page", side_effect=fetch):
            recommended = reels_music.recommend_reels_audio(
                "fitness", {"energy": "high"}, vocals="any")
        self.assertEqual(recommended["catalog_status"], "chart")
        self.assertEqual(recommended["selected"]["title"], "FE!N")
        self.assertEqual(recommended["selected"]["url"],
                         "https://www.instagram.com/reels/audio/123456789/")
        self.assertEqual(len(recommended["alternatives"]), 2)
        self.assertFalse(recommended["audio_automatically_embedded"])

    def test_instrumental_preference_promotes_only_verified_label(self):
        with patch.object(reels_music, "_fetch_public_page", return_value=self.CHART):
            result = reels_music.recommend_reels_audio(
                "fitness", {"energy": "medium"}, vocals="instrumental")
        self.assertEqual(result["selected"]["title"], "POWER (Instrumental)")
        self.assertEqual(result["selected"]["vocals"], "instrumental")
        self.assertTrue(result["selected"]["open_url"].startswith("https://soundmatcha.com/"))

    def test_network_failure_uses_verified_public_reels_audio_pages(self):
        with patch.object(reels_music, "_fetch_public_page", side_effect=OSError("offline")):
            result = reels_music.recommend_reels_audio("fitness", {"energy": "high"})
        self.assertEqual(result["catalog_status"], "curated_fallback")
        self.assertEqual(result["selected"]["title"], "FE!N (feat. Playboi Carti)")
        self.assertTrue(result["selected"]["open_url"].startswith(
            "https://www.instagram.com/reels/audio/"))

    def test_no_arbitrary_page_fetch(self):
        with self.assertRaises(ValueError):
            reels_music._fetch_public_page("http://127.0.0.1:8000/api/jobs")
        with self.assertRaises(ValueError):
            reels_music._fetch_public_page("https://evil.example/sound/test")
        with self.assertRaises(ValueError):
            reels_music.recommend_reels_audio("fitness", vocals="faked")


if __name__ == "__main__":
    unittest.main()
