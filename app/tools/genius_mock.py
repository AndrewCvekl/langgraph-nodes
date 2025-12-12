"""Genius API service for lyrics search.

Integrates with the Genius API for searching songs by lyrics.
Falls back to mock mode if GENIUS_ACCESS_TOKEN is not configured.
"""

import os
import logging
from difflib import SequenceMatcher

from dotenv import load_dotenv

# Load .env file from project root (relative to this file)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
env_path = os.path.join(project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
else:
    from dotenv import find_dotenv
    found = find_dotenv()
    if found:
        load_dotenv(found)
    else:
        load_dotenv()

logger = logging.getLogger(__name__)


# Sample song database for mock mode
SAMPLE_SONGS = [
    {"title": "Bohemian Rhapsody", "artist": "Queen", "genius_id": "genius_1",
     "lyrics_snippet": "Is this the real life? Is this just fantasy?"},
    {"title": "Hotel California", "artist": "Eagles", "genius_id": "genius_2",
     "lyrics_snippet": "On a dark desert highway, cool wind in my hair"},
    {"title": "Stairway to Heaven", "artist": "Led Zeppelin", "genius_id": "genius_3",
     "lyrics_snippet": "There's a lady who's sure all that glitters is gold"},
    {"title": "Smells Like Teen Spirit", "artist": "Nirvana", "genius_id": "genius_4",
     "lyrics_snippet": "With the lights out, it's less dangerous"},
    {"title": "Imagine", "artist": "John Lennon", "genius_id": "genius_5",
     "lyrics_snippet": "Imagine there's no heaven, it's easy if you try"},
    {"title": "Like a Rolling Stone", "artist": "Bob Dylan", "genius_id": "genius_6",
     "lyrics_snippet": "How does it feel to be on your own"},
    {"title": "Purple Haze", "artist": "Jimi Hendrix", "genius_id": "genius_7",
     "lyrics_snippet": "Purple haze all in my brain"},
    {"title": "Billie Jean", "artist": "Michael Jackson", "genius_id": "genius_8",
     "lyrics_snippet": "She was more like a beauty queen from a movie scene"},
    {"title": "Sweet Child O' Mine", "artist": "Guns N' Roses", "genius_id": "genius_9",
     "lyrics_snippet": "She's got a smile that it seems to me"},
    {"title": "Back to Black", "artist": "Amy Winehouse", "genius_id": "genius_10",
     "lyrics_snippet": "He left no time to regret, kept his dick wet"},
    {"title": "Rehab", "artist": "Amy Winehouse", "genius_id": "genius_11",
     "lyrics_snippet": "They tried to make me go to rehab, I said no, no, no"},
    {"title": "For Those About to Rock", "artist": "AC/DC", "genius_id": "genius_12",
     "lyrics_snippet": "We salute you, for those about to rock"},
    {"title": "Breaking the Law", "artist": "Judas Priest", "genius_id": "genius_13",
     "lyrics_snippet": "Breaking the law, breaking the law"},
]


def _similarity(a: str, b: str) -> float:
    """Calculate similarity ratio between two strings."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


class GeniusService:
    """Genius API service for lyrics search.
    
    Uses the Genius API to search for songs by lyrics.
    Falls back to mock mode with fuzzy matching if API token is not configured.
    """
    
    def __init__(self, songs: list[dict] | None = None):
        """Initialize the Genius service.
        
        Args:
            songs: Optional list of song dictionaries for mock mode.
        """
        self.access_token = os.getenv("GENIUS_ACCESS_TOKEN")
        self.songs = songs or SAMPLE_SONGS
        
        if self.access_token:
            logger.info("[Genius] Initialized with real API")
        else:
            logger.info("[Genius] No API token configured, using mock mode")
    
    @property
    def is_live(self) -> bool:
        """Check if using real API or mock mode."""
        return self.access_token is not None
    
    def search_by_lyrics(self, lyrics: str) -> list[dict]:
        """Search for songs by lyrics snippet.
        
        Args:
            lyrics: Lyrics snippet to search for.
            
        Returns:
            List of matching songs sorted by score (best first).
            Each dict has: title, artist, score, genius_id
        """
        if not lyrics or not lyrics.strip():
            return []
        
        if self.is_live:
            return self._search_real(lyrics)
        else:
            return self._search_mock(lyrics)
    
    def _search_real(self, lyrics: str) -> list[dict]:
        """Search using the real Genius API."""
        try:
            import requests
            
            url = "https://api.genius.com/search"
            params = {
                "access_token": self.access_token,
                "q": lyrics
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            hits = data.get('response', {}).get('hits', [])
            
            if not hits:
                logger.info(f"[Genius] No results for: {lyrics[:30]}...")
                return []
            
            results = []
            for i, hit in enumerate(hits[:5]):  # Top 5 results
                if hit.get('type') == 'song':
                    result = hit.get('result', {})
                    artist_info = result.get('primary_artist', {})
                    
                    title = result.get('title', 'Unknown').strip()
                    artist = artist_info.get('name', 'Unknown').strip()
                    genius_id = str(result.get('id', f'genius_{i}'))
                    
                    # Score based on position (first result is best)
                    score = round(1.0 - (i * 0.15), 3)
                    
                    results.append({
                        "title": title,
                        "artist": artist,
                        "score": score,
                        "genius_id": genius_id,
                    })
            
            logger.info(f"[Genius] Search for '{lyrics[:30]}...' found {len(results)} matches")
            return results
            
        except ImportError:
            logger.warning("[Genius] requests package not installed, falling back to mock")
            return self._search_mock(lyrics)
        except Exception as e:
            logger.error(f"[Genius] API error: {e}")
            return self._search_mock(lyrics)
    
    def _search_mock(self, lyrics: str) -> list[dict]:
        """Search using fuzzy matching against sample database."""
        results = []
        lyrics_lower = lyrics.lower()
        
        for song in self.songs:
            snippet = song.get("lyrics_snippet", "").lower()
            
            # Calculate similarity score
            score = _similarity(lyrics_lower, snippet)
            
            # Boost if lyrics is a substring
            if lyrics_lower in snippet:
                score = max(score, 0.8)
            
            # Only include if there's some match
            if score > 0.2:
                results.append({
                    "title": song["title"],
                    "artist": song["artist"],
                    "score": round(score, 3),
                    "genius_id": song["genius_id"],
                })
        
        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        
        logger.info(f"[Genius/Mock] Search for '{lyrics[:30]}...' found {len(results)} matches")
        return results
    
    def get_song_by_id(self, genius_id: str) -> dict | None:
        """Get a song by its Genius ID.
        
        Note: Only works in mock mode. Real API would need a separate endpoint.
        
        Args:
            genius_id: Genius ID to look up.
            
        Returns:
            Song dict or None if not found.
        """
        for song in self.songs:
            if song["genius_id"] == genius_id:
                return {
                    "title": song["title"],
                    "artist": song["artist"],
                    "genius_id": song["genius_id"],
                    "lyrics_snippet": song.get("lyrics_snippet", ""),
                }
        return None


# Global instance for convenience
_genius: GeniusService | None = None


def get_genius() -> GeniusService:
    """Get the global Genius service instance."""
    global _genius
    if _genius is None:
        _genius = GeniusService()
    return _genius
