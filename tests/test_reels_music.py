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

    def test_actual_chart_structure_separate_image_and_plain_text_rankings(self):
        page = """
        <div><a href="/sound/raindance-dave-tems/">Raindance</a>
        <p>Dave &amp; Tems</p></div>
        <div><a href="/sound/thunderstruck-ac-dc/">Thunderstruck</a>
        <p>AC/DC</p></div>
        <div><a href="/sound/fe-n-feat-playboi-carti-travis-scott/">FE!N</a>
        <p>Travis Scott</p></div>
        <ul>
        <li>1. <b>Raindance</b> — Dave &amp; Tems: <b>2M</b> Reels</li>
        <li>2. <b>Thunderstruck</b> — AC/DC: <b>282K</b> Reels</li>
        <li>3. <b>FE!N (feat. Playboi Carti)</b> — Travis Scott: <b>571K</b> Reels</li>
        </ul>
        """
        results = reels_music.parse_chart(page)
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0]["artist"], "Dave & Tems")
        self.assertEqual(results[1]["title"], "Thunderstruck")
        self.assertEqual(results[2]["artist"], "Travis Scott")
        self.assertEqual(results[2]["rank"], 3)
        self.assertIn("fe-n-feat-playboi-carti", results[2]["source_url"])

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

    def test_verified_tempo_ranks_compatible_music_above_otherwise_equal_track(self):
        candidates = [
            {"title": "Workout", "artist": "Artist", "bpm": 98},
            {"title": "Workout", "artist": "Artist", "bpm": 150},
            {"title": "Workout", "artist": "Artist", "bpm": 75},
        ]
        with patch.object(reels_music, "_chart_cached", return_value=tuple(candidates)):
            with patch.object(reels_music, "_instagram_url", return_value=None):
                result = reels_music.recommend_reels_audio(
                    "fitness", {"energy": "high", "bpm": 150}, limit=3)
        self.assertEqual(result["selected"]["bpm"], 150)
        self.assertTrue(result["selected"]["tempo_match_verified"])
        self.assertEqual(result["target_bpm"], 150)

    def test_half_time_and_double_time_are_compatible(self):
        self.assertGreater(reels_music._tempo_fit(75, 150), 2.9)
        self.assertGreater(reels_music._tempo_fit(150, 150), 2.9)
        self.assertEqual(reels_music._verified_bpm({"bpm": "unknown"}), None)
        self.assertEqual(reels_music._verified_bpm({"bpm": True}), None)
        self.assertEqual(reels_music._verified_bpm({"bpm": 999}), None)

    def test_unverified_tempo_does_not_claim_music_match(self):
        with patch.object(reels_music, "_fetch_public_page", side_effect=OSError("offline")):
            result = reels_music.recommend_reels_audio(
                "fitness", {"energy": "high", "bpm": 154})
        self.assertIsNone(result["selected"]["bpm"])
        self.assertFalse(result["selected"]["tempo_match_verified"])
        self.assertEqual(result["target_bpm"], 154)

    def test_no_arbitrary_page_fetch(self):
        with self.assertRaises(ValueError):
            reels_music._fetch_public_page("http://127.0.0.1:8000/api/jobs")
        with self.assertRaises(ValueError):
            reels_music._fetch_public_page("https://evil.example/sound/test")
        with self.assertRaises(ValueError):
            reels_music.recommend_reels_audio("fitness", vocals="faked")


if __name__ == "__main__":
    unittest.main()
