"""Recommend REAL Instagram Reels music using public thematic charts.

This module never downloads, proxies, records or embeds copyrighted audio.
A recommended track is attached natively inside the Instagram app, where Meta
can apply the appropriate account / territory / rights-holder permissions.
"""
from __future__ import annotations

import html
import math
import re
import time
from functools import lru_cache
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

SOURCE = "https://soundmatcha.com"
CHARTS = {
    "fitness": {"high": "/for/gym/", "medium": "/for/gym/", "low": "/mood/steady/"},
    "sport": {"high": "/mood/energetic/", "medium": "/for/gym/", "low": "/mood/energetic/"},
    "motivation": {"high": "/mood/powerful/", "medium": "/mood/cinematic/", "low": "/mood/cinematic/"},
    "lifestyle": {"high": "/mood/upbeat/", "medium": "/mood/warm/", "low": "/mood/warm/"},
    "auto": {"high": "/mood/energetic/", "medium": "/for/gym/", "low": "/mood/cinematic/"},
}
AUDIO_RE = re.compile(r"https://(?:www\.)?instagram\.com/reels/audio/\d+(?:/[a-zA-Z0-9_-]+)?/?")
FALLBACK = [
    {"title": "FE!N (feat. Playboi Carti)", "artist": "Travis Scott",
     "url": "https://www.instagram.com/reels/audio/7572714589408356/",
     "source_url": SOURCE + "/sound/fe-n-feat-playboi-carti-travis-scott/",
     "energy": "high", "rank": 18, "vocals": "unknown"},
    {"title": "Thunderstruck", "artist": "AC/DC",
     "url": "https://www.instagram.com/reels/audio/1922235378067874/",
     "source_url": SOURCE + "/sound/thunderstruck-ac-dc/",
     "energy": "high", "rank": 42, "vocals": "unknown"},
    {"title": "Stronger", "artist": "Kanye West",
     "url": "https://www.instagram.com/reels/audio/853805644986170/",
     "source_url": SOURCE + "/sound/stronger-kanye-west/",
     "energy": "medium", "rank": 54, "vocals": "unknown"},
    {"title": "Raindance", "artist": "Dave & Tems",
     "url": "https://www.instagram.com/reels/audio/720819121018753/raindance/",
     "source_url": SOURCE + "/sound/raindance-dave-tems/",
     "energy": "medium", "rank": 1, "vocals": "unknown"},
    {"title": "Levels", "artist": "Avicii",
     "url": "https://www.instagram.com/reels/audio/2059883887584285/",
     "source_url": SOURCE + "/sound/levels-avicii/",
     "energy": "high", "rank": 9, "vocals": "unknown"},
    {"title": "Mafia Style", "artist": "TRAP MAFIA HOUSE",
     "url": "https://www.instagram.com/reels/audio/3324876717711076/",
     "source_url": SOURCE + "/sound/mafia-style-trap-mafia-house/",
     "energy": "high", "rank": 9, "vocals": "unknown"},
]


def _fetch_public_page(url: str) -> str:
    """Fetch allowlisted metadata only, bounded in time and size."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "soundmatcha.com":
        raise ValueError("Domaine musical non autorisé")
    req = Request(url, headers={"User-Agent": "MonteurStudio/1.1 (+public music attribution)"})
    with urlopen(req, timeout=4) as response:
        return response.read(750_000).decode("utf-8", errors="replace")


class _ChartParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.current = None
        self.items: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        at = dict(attrs)
        if tag == "a":
            href = at.get("href") or ""
            parsed = urlparse(urljoin(SOURCE, href))
            if parsed.netloc == "soundmatcha.com" and parsed.path.startswith("/sound/"):
                self.current = {"source_url": urljoin(SOURCE, href), "raw": ""}
        if tag == "img" and self.current is not None:
            alt = at.get("alt") or ""
            if " — " in alt:
                self.current["raw"] = alt

    def handle_data(self, data: str) -> None:
        if self.current and not self.current["raw"]:
            self.current["raw"] = data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.current:
            raw = html.unescape(self.current["raw"]).strip()
            if " — " in raw:
                title, artist = raw.rsplit(" — ", 1)
                if title.strip() and artist.strip():
                    self.items.append({"title": title.strip()[:160],
                                       "artist": artist.strip()[:140],
                                       "source_url": self.current["source_url"],
                                       "rank": len(self.items) + 1,
                                       "vocals": "instrumental" if "instrumental" in title.lower()
                                                 else "unknown"})
            self.current = None


def parse_chart(page: str) -> list[dict]:
    parser = _ChartParser()
    parser.feed(page)
    unique: dict[str, dict] = {}
    for item in parser.items:
        unique.setdefault(item["source_url"], item)
    return list(unique.values())[:50]


@lru_cache(maxsize=24)
def _chart_cached(path: str, period: int) -> tuple[dict, ...]:
    return tuple(parse_chart(_fetch_public_page(SOURCE + path)))


def _instagram_url(source_url: str) -> str | None:
    try:
        result = AUDIO_RE.search(_fetch_public_page(source_url))
        return result.group(0) if result else None
    except (OSError, ValueError, TimeoutError):
        return None


def _score(item: dict, energy: str, index: int, vocals: str) -> float:
    # Chart rank and visible artistic clues; BPM/lyrics are NOT fabricated.
    title = item["title"].lower()
    artist = item["artist"].lower()
    high = ("fe!n", "thunder", "stronger", "mafia", "freak", "rock",
            "metal", "fire", "power", "level", "energy", "rush", "hard", "sprint")
    soft = ("dream", "calm", "heaven", "lovely", "sun", "slow",
            "luther", "rain", "focus", "acoustic", "warm")
    weight = 3.0 / (1 + math.log1p(index + 1))
    weight += 2.2 if energy == "high" and any(term in title for term in high) else 0
    weight += 1.8 if energy == "low" and any(term in title for term in soft) else 0
    weight += 0.5 if energy == "medium" and any(term in title for term in ("move", "strong", "work", "feel")) else 0
    if item.get("energy") == energy:
        weight += 1.0
    if vocals == "instrumental" and item.get("vocals") == "instrumental":
        weight += 4.5
    if vocals == "instrumental" and item.get("vocals") != "instrumental":
        weight -= 1.2
    if vocals == "vocals" and item.get("vocals") == "instrumental":
        weight -= 3
    if artist in {"unknown", "original audio"}:
        weight -= 0.8
    return round(weight, 4)


def recommend_reels_audio(theme: str, profile: dict | None = None,
                          vocals: str = "any", limit: int = 3) -> dict:
    """Pick tracks used on Reels that fit the clip's visual pace and content niche.

    Native selection in Instagram is required: popularity is not permission for
    a separate editor to insert the sound recording into the MP4.
    """
    if vocals not in {"any", "instrumental", "vocals"}:
        raise ValueError("Préférence musicale inconnue")
    energy = (profile or {}).get("energy", "medium")
    if energy not in {"low", "medium", "high"}:
        energy = "medium"
    route = CHARTS.get(theme, CHARTS["auto"])
    chart_path = route.get(energy, route["medium"])
    chart_url = SOURCE + chart_path
    catalog_source = "chart"
    try:
        catalog = list(_chart_cached(chart_path, int(time.time() // (12 * 3600))))
        if not catalog:
            raise ValueError("Catalogue musical vide")
    except (OSError, ValueError, TimeoutError):
        catalog = [dict(item) for item in FALLBACK]
        catalog_source = "curated_fallback"
    ranked = sorted(enumerate(catalog), key=lambda pair:
                    (-_score(pair[1], energy, pair[0], vocals), pair[0]))
    output = []
    for index, entry in ranked:
        candidate = dict(entry)
        candidate["score"] = _score(entry, energy, index, vocals)
        candidate["reels_rank"] = candidate.pop("rank", index + 1)
        candidate["url"] = candidate.get("url") or _instagram_url(candidate["source_url"])
        # If Instagram temporarily throttles metadata, the cited source page
        # still provides the official audio deep-link.
        candidate["open_url"] = candidate["url"] or candidate["source_url"]
        output.append(candidate)
        if len(output) >= max(1, min(limit, 5)):
            break
    return {
        "selected": output[0] if output else None,
        "alternatives": output[1:],
        "visual_energy": energy,
        "matching": "video_motion_and_similar_reels_category",
        "source": "SoundMatcha public Instagram Reels audio charts",
        "catalog_status": catalog_source,
        "catalog_url": chart_url if catalog_source == "chart" else SOURCE + "/for/gym/",
        "audio_automatically_embedded": False,
        "application": "Add the selected track inside Instagram when publishing",
        "availability_and_license": "Check Instagram account, territory, personal/commercial use",
        "note": "Track tempo and presence of vocals not verified unless explicitly labeled."
    }
