"""Tools for the music store support bot."""

from app.tools.db_tools import (
    get_customer_contact,
    update_customer_email,
    find_track_by_title_artist,
    create_invoice_for_track,
    get_albums_by_artist,
    get_tracks_by_artist,
    check_for_songs,
)
from app.tools.twilio_mock import TwilioService, get_twilio
from app.tools.genius_mock import GeniusService, get_genius
from app.tools.youtube_mock import YouTubeService, get_youtube
from app.tools.payment_mock import PaymentMock

# Backward compatibility aliases
TwilioMock = TwilioService
GeniusMock = GeniusService
YouTubeMock = YouTubeService

__all__ = [
    # DB tools
    "get_customer_contact",
    "update_customer_email",
    "find_track_by_title_artist",
    "create_invoice_for_track",
    "get_albums_by_artist",
    "get_tracks_by_artist",
    "check_for_songs",
    # Services (real API with mock fallback)
    "TwilioService",
    "GeniusService", 
    "YouTubeService",
    "PaymentMock",
    # Service getters
    "get_twilio",
    "get_genius",
    "get_youtube",
    # Backward compatibility aliases
    "TwilioMock",
    "GeniusMock",
    "YouTubeMock",
]

