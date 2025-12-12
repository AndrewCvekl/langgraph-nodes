"""YouTube API service for video search.

Integrates with the YouTube Data API v3 for searching videos.
Falls back to mock mode if YOUTUBE_API_KEY is not configured.
"""

import os
import hashlib
import logging

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


class YouTubeService:
    """YouTube API service for video search.
    
    Uses the YouTube Data API v3 to search for videos.
    Falls back to deterministic mock responses if API key is not configured.
    """
    
    def __init__(self):
        """Initialize the YouTube service."""
        self.api_key = os.getenv("YOUTUBE_API_KEY")
        self._client = None
        
        if self.api_key:
            try:
                from googleapiclient.discovery import build
                self._client = build('youtube', 'v3', developerKey=self.api_key)
                logger.info("[YouTube] Initialized with real API")
            except ImportError:
                logger.warning("[YouTube] google-api-python-client not installed, using mock mode")
            except Exception as e:
                logger.warning(f"[YouTube] Failed to initialize API client: {e}, using mock mode")
        else:
            logger.info("[YouTube] No API key configured, using mock mode")
    
    @property
    def is_live(self) -> bool:
        """Check if using real API or mock mode."""
        return self._client is not None
    
    def search_video(self, query: str) -> dict:
        """Search for a YouTube video.
        
        Args:
            query: Search query (e.g., "Song Title Artist official audio").
            
        Returns:
            Dict with video_id, title, url, and channel.
        """
        if not query or not query.strip():
            return self._empty_result()
        
        if self._client:
            return self._search_real(query)
        else:
            return self._search_mock(query)
    
    def _search_real(self, query: str) -> dict:
        """Search using the real YouTube API."""
        try:
            search_response = self._client.search().list(
                q=query,
                part='id,snippet',
                maxResults=1,
                type='video',
                videoEmbeddable='true'
            ).execute()
            
            items = search_response.get('items', [])
            if not items:
                logger.info(f"[YouTube] No videos found for: {query[:50]}")
                return self._empty_result()
            
            video = items[0]
            video_id = video['id']['videoId']
            title = video['snippet']['title']
            channel = video['snippet']['channelTitle']
            url = f"https://www.youtube.com/watch?v={video_id}"
            
            logger.info(f"[YouTube] Found: {title} ({video_id})")
            
            return {
                "video_id": video_id,
                "title": title,
                "url": url,
                "channel": channel,
            }
            
        except Exception as e:
            logger.error(f"[YouTube] API error: {e}")
            # Fall back to mock on error
            return self._search_mock(query)
    
    def _search_mock(self, query: str) -> dict:
        """Generate a mock response for testing."""
        video_id = self._generate_video_id(query)
        title = self._format_title(query)
        url = f"https://www.youtube.com/watch?v={video_id}"
        
        logger.info(f"[YouTube/Mock] Generated: {title} ({video_id})")
        
        return {
            "video_id": video_id,
            "title": title,
            "url": url,
            "channel": "Mock Channel",
        }
    
    def _empty_result(self) -> dict:
        """Return an empty/default result."""
        return {
            "video_id": "dQw4w9WgXcQ",
            "title": "Unknown Video",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "channel": "Unknown",
        }
    
    def _generate_video_id(self, query: str) -> str:
        """Generate a deterministic 11-character video ID from query."""
        hash_bytes = hashlib.md5(query.encode()).hexdigest()[:11]
        return hash_bytes.replace('a', 'A').replace('e', 'E')[:11]
    
    def _format_title(self, query: str) -> str:
        """Format the search query as a video title."""
        for suffix in [" official audio", " official video", " music video", " lyrics"]:
            query = query.lower().replace(suffix, "")
        return query.strip().title()
    
    def get_embed_html(self, video_id: str, autoplay: bool = True) -> str:
        """Generate an HTML embed iframe for a video.
        
        Args:
            video_id: YouTube video ID.
            autoplay: Whether to autoplay the video.
            
        Returns:
            HTML iframe string.
        """
        autoplay_param = "1" if autoplay else "0"
        return (
            f'<iframe width="560" height="315" '
            f'src="https://www.youtube.com/embed/{video_id}?autoplay={autoplay_param}" '
            f'frameborder="0" allow="accelerometer; autoplay; clipboard-write; '
            f'encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>'
        )


# Global instance for convenience
_youtube: YouTubeService | None = None


def get_youtube() -> YouTubeService:
    """Get the global YouTube service instance."""
    global _youtube
    if _youtube is None:
        _youtube = YouTubeService()
    return _youtube
