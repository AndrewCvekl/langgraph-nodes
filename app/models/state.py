"""State definitions for the music store support bot.

This module defines all state types used across the application:
- AppState: The main application state
- EmailFlowState: State for email update flow
- LyricsFlowState: State for lyrics search flow
- PaymentState: State for payment flow
"""

from typing import TypedDict, Literal, Optional, Any, Annotated
import operator
from langchain_core.messages import BaseMessage


class EmailFlowState(TypedDict, total=False):
    """State for the email update flow with phone verification."""
    
    status: Literal[
        "idle",
        "confirm_send",
        "await_code",
        "await_new_email",
        "done",
        "cancelled",
        "failed"
    ]
    current_email: str
    phone: str
    verification_id: str
    code_attempts_left: int
    last_code_entered: str
    proposed_email: str
    error: str


class LyricsFlowState(TypedDict, total=False):
    """State for the lyrics search flow."""
    
    status: Literal[
        "idle",
        "searching",
        "await_listen_confirm",
        "playing",
        "await_buy_or_request",
        "done"
    ]
    lyrics_query: str
    # Best match from Genius: {title, artist, score, genius_id}
    genius_best: dict
    # Track from Chinook catalogue if found: {TrackId, TrackName, UnitPrice, AlbumTitle, ArtistName}
    catalogue_track: Optional[dict]
    # YouTube video info: {video_id, title, url}
    youtube: dict


class PaymentState(TypedDict, total=False):
    """State for the payment flow."""
    
    status: Literal[
        "draft",
        "confirmed",
        "succeeded",
        "failed",
        "cancelled"
    ]
    payment_intent_id: str
    # Items to purchase: [{track_id, name, qty, unit_price}]
    items: list[dict]
    total: float
    transaction_id: str
    invoice_id: int
    error: str


class PurchaseFlowState(TypedDict, total=False):
    """State for the purchase (checkout) flow."""

    status: Literal[
        "idle",
        "resolving",
        "done",
        "cancelled",
        "failed",
    ]
    # Last free-text query the user gave us (title or "track id 123")
    query: str
    # Parsed TrackId if present in the query
    parsed_track_id: Optional[int]
    # Parsed numeric reference (may be a TrackId or a 1-based list index)
    numeric_ref: Optional[int]
    # Candidate TrackIds when multiple matches exist
    candidate_track_ids: list[int]
    # Final TrackId chosen for purchase
    selected_track_id: Optional[int]
    error: str


class AppState(TypedDict, total=False):
    """Main application state for the music store support bot.
    
    This state is shared across all nodes in the graph and contains:
    - Conversation history (messages)
    - User identification
    - Routing information
    - Feature-specific slices (email_flow, lyrics_flow, payment)
    - UI output messages
    """
    
    # Conversation - using Annotated with operator.add for append semantics
    messages: Annotated[list[BaseMessage], operator.add]
    
    # User identification - assume known or configured
    user_id: int
    
    # Last user message for easy access
    last_user_msg: str
    
    # Routing decision from router agent
    route: Literal["normal", "update_email", "lyrics_search", "purchase"]
    
    # Session-based verification status (persists until app restart)
    verified: bool
    
    # Feature-specific state slices
    email_flow: EmailFlowState
    lyrics_flow: LyricsFlowState
    payment: PaymentState
    purchase_flow: PurchaseFlowState

    # Lightweight cross-turn context for “buy it” follow-ups in normal chat.
    # When we show Track IDs, we store them here so the purchase flow can
    # resolve ambiguous references.
    last_track_ids: list[int]
    
    # UI output messages - structured payloads for the UI
    # Each message can be:
    # - {"type": "text", "text": "..."}
    # - {"type": "embed", "provider": "youtube", "html": "..."}
    # - {"type": "invoice", "invoice_id": ..., "total": ..., "lines": [...]}
    assistant_messages: list[dict]


def get_default_email_flow() -> EmailFlowState:
    """Get default email flow state."""
    return {
        "status": "idle",
        "current_email": "",
        "phone": "",
        "verification_id": "",
        "code_attempts_left": 3,
        "last_code_entered": "",
        "proposed_email": "",
        "error": "",
    }


def get_default_lyrics_flow() -> LyricsFlowState:
    """Get default lyrics flow state."""
    return {
        "status": "idle",
        "lyrics_query": "",
        "genius_best": {},
        "catalogue_track": None,
        "youtube": {},
    }


def get_default_payment() -> PaymentState:
    """Get default payment state."""
    return {
        "status": "draft",
        "payment_intent_id": "",
        "items": [],
        "total": 0.0,
        "transaction_id": "",
        "invoice_id": 0,
        "error": "",
    }


def get_default_purchase_flow() -> PurchaseFlowState:
    return {
        "status": "idle",
        "query": "",
        "parsed_track_id": None,
        "numeric_ref": None,
        "candidate_track_ids": [],
        "selected_track_id": None,
        "error": "",
    }


def get_initial_state(user_id: int) -> AppState:
    """Get initial application state for a new conversation."""
    return {
        "messages": [],
        "user_id": user_id,
        "last_user_msg": "",
        "route": "normal",
        "verified": False,
        "email_flow": get_default_email_flow(),
        "lyrics_flow": get_default_lyrics_flow(),
        "payment": get_default_payment(),
        "purchase_flow": get_default_purchase_flow(),
        "last_track_ids": [],
        "assistant_messages": [],
    }

