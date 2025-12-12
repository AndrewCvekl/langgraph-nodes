"""Lyrics search subgraph with YouTube playback and purchase option.

This subgraph handles the lyrics identification flow:
1. Extract lyrics query from user message
2. Search Genius for matching song
3. Check if song is in our catalogue
4. Ask user if they want to listen
5. Search YouTube and show player
6. Offer to buy (if in catalogue) or request (if not)
7. Invoke payment subgraph if buying

Uses interrupts for user confirmations.
"""

import re
from typing import Literal

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command

from app.models.state import AppState
from app.db import get_engine
from app.tools.db_tools import find_track_by_title_artist, check_track_already_purchased
from app.tools.genius_mock import get_genius
from app.tools.youtube_mock import get_youtube
from app.graphs.payment_subgraph import payment_subgraph


def add_assistant_message(state: AppState, msg: dict | str) -> list[dict]:
    """Helper to add a message to assistant_messages."""
    current = state.get("assistant_messages", []) or []
    if isinstance(msg, str):
        msg = {"type": "text", "text": msg}
    return current + [msg]


def extract_lyrics_from_message(message: str) -> str:
    """Extract lyrics snippet from user message.
    
    Looks for common patterns like:
    - "song that goes like ..."
    - "lyrics that say ..."
    - Quoted text
    - Falls back to the whole message
    """
    # Try to find quoted text
    quoted = re.findall(r'["\'](.+?)["\']', message)
    if quoted:
        return quoted[0]
    
    # Try common patterns
    patterns = [
        r'(?:song|track|music)\s+(?:that\s+)?(?:goes|has|with)\s+(?:like\s+)?["\']?(.+)',
        r'lyrics?\s+(?:that\s+)?(?:say|go|are)\s+["\']?(.+)',
        r'looking\s+for\s+(?:a\s+)?song\s+(?:with\s+)?["\']?(.+)',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            return match.group(1).strip().strip('"\'')
    
    # Fall back to the message after removing common prefixes
    cleaned = message
    for prefix in ["what song", "which song", "find the song", "what's the song"]:
        if cleaned.lower().startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
    
    return cleaned


# Node B0: Initialize and extract lyrics query
def lyrics_init_extract(state: AppState) -> dict:
    """Extract lyrics query from the user's message."""
    last_msg = state.get("last_user_msg", "")
    lyrics_query = extract_lyrics_from_message(last_msg)
    
    return {
        "lyrics_flow": {
            "status": "searching",
            "lyrics_query": lyrics_query,
            "genius_best": {},
            "catalogue_track": None,
            "already_owned": False,
            "youtube": {},
        },
    }


# Node B1: Search Genius for matching song
def lyrics_genius_search(state: AppState) -> Command[Literal["lyrics_catalogue_lookup", "lyrics_done"]]:
    """Search Genius for songs matching the lyrics."""
    lyrics_flow = state.get("lyrics_flow", {})
    lyrics_query = lyrics_flow.get("lyrics_query", "")
    
    genius = get_genius()
    matches = genius.search_by_lyrics(lyrics_query)
    
    if not matches:
        return Command(
            update={
                "lyrics_flow": {
                    **lyrics_flow,
                    "status": "done",
                },
                "assistant_messages": add_assistant_message(
                    state,
                    "I couldn't find a song matching those lyrics. "
                    "Try providing a longer or different snippet?"
                ),
            },
            goto="lyrics_done",
        )
    
    # Take the best match
    best = matches[0]
    
    return Command(
        update={
            "lyrics_flow": {
                **lyrics_flow,
                "genius_best": best,
            },
        },
        goto="lyrics_catalogue_lookup",
    )


# Node B2: Check if song is in our catalogue and if user already owns it
def lyrics_catalogue_lookup(state: AppState) -> dict:
    """Look up the song in our catalogue and check if user already owns it.
    
    Returns a dict (not Command) so that the state update is checkpointed
    before the interrupt node runs. This ensures assistant messages display
    before the interrupt prompt.
    """
    lyrics_flow = state.get("lyrics_flow", {})
    genius_best = lyrics_flow.get("genius_best", {})
    user_id = state.get("user_id", 1)
    
    title = genius_best.get("title", "")
    artist = genius_best.get("artist", "")
    
    engine = get_engine()
    catalogue_track = find_track_by_title_artist(engine, title, artist)
    
    # Check if user already owns this track
    already_owned = False
    if catalogue_track:
        track_id = catalogue_track.get("TrackId")
        already_owned = check_track_already_purchased(engine, user_id, track_id)
    
    # Inform user about the song and catalogue/ownership status
    if catalogue_track:
        if already_owned:
            msg = (
                f"I think you're thinking of \"{title}\" by {artist}! "
                "Good news - you already own this track! 🎵"
            )
        else:
            msg = (
                f"I think you're thinking of \"{title}\" by {artist}! "
                f"Great news - it's in our catalogue for ${catalogue_track['UnitPrice']:.2f}."
            )
    else:
        msg = (
            f"I think you're thinking of \"{title}\" by {artist}. "
            "Unfortunately, it's not currently in our catalogue."
        )
    
    return {
        "lyrics_flow": {
            **lyrics_flow,
            "status": "await_listen_confirm",
            "catalogue_track": catalogue_track,
            "already_owned": already_owned,
        },
        "assistant_messages": add_assistant_message(state, msg),
    }


# Node B3: Interrupt to confirm listening
def lyrics_interrupt_listen_confirm(state: AppState) -> Command[Literal["lyrics_youtube_search", "lyrics_done"]]:
    """Interrupt to ask if user wants to listen.
    
    Includes song identification context in the interrupt payload so it displays
    even when subgraph state isn't fully propagated to parent on interrupt.
    """
    lyrics_flow = state.get("lyrics_flow", {})
    genius_best = lyrics_flow.get("genius_best", {})
    catalogue_track = lyrics_flow.get("catalogue_track")
    already_owned = lyrics_flow.get("already_owned", False)
    
    title = genius_best.get("title", "")
    artist = genius_best.get("artist", "")
    
    # Build context message to show before the question
    if catalogue_track:
        if already_owned:
            context = (
                f"I think you're thinking of \"{title}\" by {artist}! "
                "Good news - you already own this track! 🎵"
            )
        else:
            context = (
                f"I think you're thinking of \"{title}\" by {artist}! "
                f"Great news - it's in our catalogue for ${catalogue_track['UnitPrice']:.2f}."
            )
    else:
        context = (
            f"I think you're thinking of \"{title}\" by {artist}. "
            "Unfortunately, it's not currently in our catalogue."
        )
    
    decision = interrupt({
        "type": "confirm",
        "title": "Song Identified",
        "context": context,  # Pre-question context message
        "text": "Would you like to have a listen?",
        "choices": ["Yes", "No"],
    })
    
    if decision == "Yes":
        return Command(goto="lyrics_youtube_search")
    else:
        return Command(
            update={
                "assistant_messages": add_assistant_message(
                    state, "No problem! Let me know if you'd like help with anything else."
                ),
            },
            goto="lyrics_done",
        )


# Node B4: Search YouTube for the song
def lyrics_youtube_search(state: AppState) -> dict:
    """Search YouTube for the song."""
    lyrics_flow = state.get("lyrics_flow", {})
    genius_best = lyrics_flow.get("genius_best", {})
    
    title = genius_best.get("title", "")
    artist = genius_best.get("artist", "")
    
    youtube = get_youtube()
    query = f"{title} {artist} official audio"
    video = youtube.search_video(query)
    
    return {
        "lyrics_flow": {
            **lyrics_flow,
            "status": "playing",
            "youtube": video,
        },
    }


# Node B5: Render player and make offer message
def lyrics_render_player_and_offer(state: AppState) -> Command[Literal["lyrics_interrupt_buy_confirm", "lyrics_interrupt_request_confirm", "lyrics_done"]]:
    """Render the YouTube player and prepare the offer message.

    Routes based on catalogue status and ownership:
    - Already owned: just show player and finish
    - In catalogue (not owned): offer to purchase
    - Not in catalogue: offer to request addition
    """
    lyrics_flow = state.get("lyrics_flow", {})
    youtube_info = lyrics_flow.get("youtube", {})
    catalogue_track = lyrics_flow.get("catalogue_track")
    already_owned = lyrics_flow.get("already_owned", False)

    video_id = youtube_info.get("video_id", "")

    # Create embed message
    yt = get_youtube()
    embed_html = yt.get_embed_html(video_id, autoplay=True)

    messages = state.get("assistant_messages", []) or []
    messages = messages + [{
        "type": "embed",
        "provider": "youtube",
        "video_id": video_id,
        "url": youtube_info.get("url", ""),
        "html": embed_html,
    }]

    # Determine routing based on catalogue status and ownership
    if already_owned:
        # User already owns this track - just show player and finish
        messages = messages + [{
            "type": "text",
            "text": "Enjoy your music! Let me know if you need anything else.",
        }]
        goto = "lyrics_done"
    elif catalogue_track:
        # Song is in catalogue but not owned - route to purchase interrupt
        goto = "lyrics_interrupt_buy_confirm"
    else:
        # Song not in catalogue - route to request interrupt
        goto = "lyrics_interrupt_request_confirm"

    return Command(
        update={
            "lyrics_flow": {
                **lyrics_flow,
                "status": "done" if already_owned else "await_buy_or_request",
            },
            "assistant_messages": messages,
        },
        goto=goto,
    )


# Node B6: Interrupt to confirm purchase
def lyrics_interrupt_buy_confirm(state: AppState) -> Command[Literal["lyrics_invoke_payment", "lyrics_done"]]:
    """Interrupt to confirm purchase.

    Includes player context in the interrupt payload.
    """
    lyrics_flow = state.get("lyrics_flow", {})
    catalogue_track = lyrics_flow.get("catalogue_track", {})
    youtube_info = lyrics_flow.get("youtube", {})
    price = catalogue_track.get("UnitPrice", 0.99) if catalogue_track else 0.99

    # Context shows the player info
    context = f"🎵 Now playing: {youtube_info.get('url', '')}"

    decision = interrupt({
        "type": "confirm",
        "title": "Purchase Track",
        "context": context,
        "text": f"Would you like to purchase this track for ${price:.2f}?",
        "choices": ["Yes", "No"],
    })

    if decision == "Yes":
        return Command(goto="lyrics_invoke_payment")
    else:
        return Command(
            update={
                "assistant_messages": add_assistant_message(
                    state, "No worries! Enjoy the preview. Let me know if you need anything else."
                ),
            },
            goto="lyrics_done",
        )




# Node B7: Invoke payment subgraph
def lyrics_invoke_payment(state: AppState) -> dict:
    """Prepare and invoke the payment subgraph."""
    lyrics_flow = state.get("lyrics_flow", {})
    catalogue_track = lyrics_flow.get("catalogue_track", {})
    
    if not catalogue_track:
        return {
            "assistant_messages": add_assistant_message(
                state, "Sorry, there was an error finding the track. Please try again."
            ),
        }
    
    # Set up payment state
    items = [{
        "track_id": catalogue_track.get("TrackId"),
        "name": catalogue_track.get("TrackName"),
        "qty": 1,
        "unit_price": catalogue_track.get("UnitPrice", 0.99),
    }]
    
    return {
        "payment": {
            "status": "draft",
            "payment_intent_id": "",
            "items": items,
            "total": items[0]["unit_price"],
            "transaction_id": "",
            "invoice_id": 0,
            "error": "",
        },
    }


# Node B8: Interrupt to confirm request
def lyrics_interrupt_request_confirm(state: AppState) -> Command[Literal["lyrics_done"]]:
    """Interrupt to confirm catalogue request.
    
    Includes player context in the interrupt payload.
    """
    lyrics_flow = state.get("lyrics_flow", {})
    youtube_info = lyrics_flow.get("youtube", {})
    
    # Context shows the player info
    context = f"🎵 Now playing: {youtube_info.get('url', '')}"
    
    decision = interrupt({
        "type": "confirm",
        "title": "Request Song",
        "context": context,
        "text": "Is this the sort of song you'd like to see added to our catalogue?",
        "choices": ["Yes", "No"],
    })
    
    if decision == "Yes":
        return Command(
            update={
                "assistant_messages": add_assistant_message(
                    state,
                    "Great! I've noted your interest. We'll consider adding this song "
                    "to our catalogue. Is there anything else I can help with?"
                ),
            },
            goto="lyrics_done",
        )
    else:
        return Command(
            update={
                "assistant_messages": add_assistant_message(
                    state, "No worries! Enjoy the preview. Let me know if you need anything else."
                ),
            },
            goto="lyrics_done",
        )


# Node B9: Done (terminal node)
def lyrics_done(state: AppState) -> dict:
    """Terminal node for lyrics flow."""
    lyrics_flow = state.get("lyrics_flow", {})
    return {
        "lyrics_flow": {
            **lyrics_flow,
            "status": "done",
        },
    }


def create_lyrics_subgraph() -> StateGraph:
    """Create the lyrics search subgraph."""
    builder = StateGraph(AppState)
    
    # Add all nodes
    builder.add_node("lyrics_init_extract", lyrics_init_extract)
    builder.add_node("lyrics_genius_search", lyrics_genius_search)
    builder.add_node("lyrics_catalogue_lookup", lyrics_catalogue_lookup)
    builder.add_node("lyrics_interrupt_listen_confirm", lyrics_interrupt_listen_confirm)
    builder.add_node("lyrics_youtube_search", lyrics_youtube_search)
    builder.add_node("lyrics_render_player_and_offer", lyrics_render_player_and_offer)
    builder.add_node("lyrics_interrupt_buy_confirm", lyrics_interrupt_buy_confirm)
    builder.add_node("lyrics_invoke_payment", lyrics_invoke_payment)
    builder.add_node("lyrics_interrupt_request_confirm", lyrics_interrupt_request_confirm)
    # Add payment subgraph directly as a node
    builder.add_node("payment_flow", payment_subgraph)
    builder.add_node("lyrics_done", lyrics_done)
    
    # Add edges
    # Entry point
    builder.set_entry_point("lyrics_init_extract")
    builder.add_edge("lyrics_init_extract", "lyrics_genius_search")
    
    # lyrics_genius_search uses Command to route to lyrics_catalogue_lookup or lyrics_done
    
    # lyrics_catalogue_lookup returns dict, use edge to interrupt
    # This ensures assistant message is checkpointed before interrupt fires
    builder.add_edge("lyrics_catalogue_lookup", "lyrics_interrupt_listen_confirm")
    
    # lyrics_interrupt_listen_confirm uses Command to route based on user choice
    
    # YouTube search and player rendering
    builder.add_edge("lyrics_youtube_search", "lyrics_render_player_and_offer")
    
    # lyrics_render_player_and_offer uses Command to route to buy or request interrupt
    # based on catalogue status
    
    # Payment flow
    builder.add_edge("lyrics_invoke_payment", "payment_flow")
    builder.add_edge("payment_flow", "lyrics_done")
    
    # Terminal
    builder.add_edge("lyrics_done", END)
    
    return builder


# Compile the subgraph (without checkpointer - parent provides it)
lyrics_subgraph = create_lyrics_subgraph().compile()

