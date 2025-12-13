"""Purchase subgraph for song-level checkout.

Goal: a single, LangGraph-native purchase flow that works from *any* entry point:
- "buy track 123"
- "can I buy it?" after seeing a track list
- "purchase <song title>"

This subgraph:
1) Resolves a target track (TrackId) deterministically using state + DB lookups
2) Confirms via interrupt (or delegates to payment_subgraph confirmation)
3) Invokes payment_subgraph to charge + create invoice + render receipt

Design notes:
- Keep purchase at a *song (track) level* only.
- Use interrupts for any missing/ambiguous user input.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from langgraph.graph import StateGraph, END
from langgraph.types import Command, interrupt

from app.db import get_engine
from app.models.state import AppState
from app.tools.db_tools import check_track_already_purchased
from app.graphs.payment_subgraph import payment_subgraph


def add_assistant_message(state: AppState, msg: dict | str) -> list[dict]:
    current = state.get("assistant_messages", []) or []
    if isinstance(msg, str):
        msg = {"type": "text", "text": msg}
    return current + [msg]


def _parse_track_id(text: str) -> Optional[int]:
    """Extract a TrackId from user text if present."""
    if not text:
        return None
    s = text.strip()
    # If the user enters ONLY a number (common CLI behavior), treat it as Track ID.
    if re.fullmatch(r"\d+", s):
        return int(s)
    # Prefer explicit "Track ID: 123" / "track id 123"
    m = re.search(r"\btrack\s*id\b\D*(\d+)\b", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    # Also accept "id 123" if user is clearly talking about purchase
    m = re.search(r"\bid\b\D*(\d+)\b", text, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _parse_first_int(text: str) -> Optional[int]:
    """Parse the first integer token in a string (e.g. 'buy 10' -> 10)."""
    if not text:
        return None
    m = re.search(r"\b(\d+)\b", text)
    return int(m.group(1)) if m else None


def _fetch_track_by_id(track_id: int) -> Optional[dict]:
    """Fetch a single track row with artist + price."""
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    Track.TrackId,
                    Track.Name AS TrackName,
                    Track.UnitPrice,
                    Artist.Name AS ArtistName,
                    Album.Title AS AlbumTitle
                FROM Track
                JOIN Album ON Track.AlbumId = Album.AlbumId
                JOIN Artist ON Album.ArtistId = Artist.ArtistId
                WHERE Track.TrackId = :track_id
                """
            ),
            {"track_id": track_id},
        ).fetchone()
    if not row:
        return None
    return {
        "TrackId": int(row[0]),
        "TrackName": row[1],
        "UnitPrice": float(row[2]),
        "ArtistName": row[3],
        "AlbumTitle": row[4],
    }


def _search_tracks_by_title(title_query: str, limit: int = 5) -> list[dict]:
    """Search tracks by title (partial match)."""
    from sqlalchemy import text

    engine = get_engine()
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    Track.TrackId,
                    Track.Name AS TrackName,
                    Track.UnitPrice,
                    Artist.Name AS ArtistName,
                    Album.Title AS AlbumTitle
                FROM Track
                JOIN Album ON Track.AlbumId = Album.AlbumId
                JOIN Artist ON Album.ArtistId = Artist.ArtistId
                WHERE Track.Name LIKE :q
                ORDER BY Track.Name
                LIMIT :limit
                """
            ),
            {"q": f"%{title_query}%", "limit": limit},
        ).fetchall()
    return [
        {
            "TrackId": int(r[0]),
            "TrackName": r[1],
            "UnitPrice": float(r[2]),
            "ArtistName": r[3],
            "AlbumTitle": r[4],
        }
        for r in rows
    ]


# Node A0: Initialize purchase attempt
def purchase_init(state: AppState) -> dict:
    last_msg = state.get("last_user_msg", "")
    parsed_track_id = _parse_track_id(last_msg)
    numeric_ref = _parse_first_int(last_msg)

    return {
        "purchase_flow": {
            "status": "resolving",
            "query": last_msg,
            "parsed_track_id": parsed_track_id,
            "numeric_ref": numeric_ref,
            "candidate_track_ids": [],
            "selected_track_id": None,
            "error": "",
        }
    }


# Node A1: Resolve which track to buy
def purchase_resolve_track(
    state: AppState,
) -> Command[
    Literal[
        "purchase_interrupt_ask_which",
        "purchase_interrupt_choose_track",
        "purchase_prepare_payment",
        "purchase_done",
    ]
]:
    pf = state.get("purchase_flow", {}) or {}
    user_id = state.get("user_id", 1)

    parsed_track_id = pf.get("parsed_track_id")
    numeric_ref = pf.get("numeric_ref")
    if parsed_track_id:
        track = _fetch_track_by_id(int(parsed_track_id))
        if not track:
            return Command(
                update={
                    "assistant_messages": add_assistant_message(
                        state,
                        f"I couldn’t find a track with Track ID {parsed_track_id}. "
                        "Please share a valid Track ID or a song title to search.",
                    )
                },
                goto="purchase_done",
            )

        already = check_track_already_purchased(get_engine(), user_id, track["TrackId"])
        if already:
            return Command(
                update={
                    "assistant_messages": add_assistant_message(
                        state,
                        f"You already own \"{track['TrackName']}\" by {track['ArtistName']}. 🎵",
                    ),
                    "last_track_ids": [track["TrackId"]],
                    "purchase_flow": {**pf, "status": "done", "selected_track_id": track["TrackId"]},
                },
                goto="purchase_done",
            )

        return Command(
            update={
                "last_track_ids": [track["TrackId"]],
                "purchase_flow": {**pf, "selected_track_id": track["TrackId"]},
            },
            goto="purchase_prepare_payment",
        )

    # No explicit Track ID: try state context (last_track_ids, lyrics_flow.catalogue_track)
    last_track_ids = state.get("last_track_ids", []) or []
    if isinstance(last_track_ids, int):
        last_track_ids = [last_track_ids]

    lyrics_track = (state.get("lyrics_flow", {}) or {}).get("catalogue_track")
    if lyrics_track and isinstance(lyrics_track, dict) and lyrics_track.get("TrackId"):
        # Prefer explicit lyrics context if it's a single concrete track and no other context exists.
        if not last_track_ids:
            last_track_ids = [int(lyrics_track["TrackId"])]

    if len(last_track_ids) == 1:
        tid = int(last_track_ids[0])
        track = _fetch_track_by_id(tid)
        if track:
            already = check_track_already_purchased(get_engine(), user_id, track["TrackId"])
            if already:
                return Command(
                    update={
                        "assistant_messages": add_assistant_message(
                            state,
                            f"You already own \"{track['TrackName']}\" by {track['ArtistName']}. 🎵",
                        ),
                        "purchase_flow": {**pf, "status": "done", "selected_track_id": track["TrackId"]},
                    },
                    goto="purchase_done",
                )
            return Command(
                update={"purchase_flow": {**pf, "selected_track_id": track["TrackId"]}},
                goto="purchase_prepare_payment",
            )

    if len(last_track_ids) > 1:
        # If the user gave a number, interpret it intelligently:
        # - If it matches a Track ID we just showed, use it as Track ID
        # - Else if it is within 1..N, treat it as list index into last_track_ids
        if isinstance(numeric_ref, int):
            if numeric_ref in last_track_ids:
                pf = {**pf, "parsed_track_id": int(numeric_ref)}
                return Command(update={"purchase_flow": pf}, goto="purchase_resolve_track")
            if 1 <= numeric_ref <= len(last_track_ids):
                chosen = int(last_track_ids[numeric_ref - 1])
                return Command(
                    update={
                        "purchase_flow": {**pf, "selected_track_id": chosen},
                        "last_track_ids": [chosen],
                    },
                    goto="purchase_prepare_payment",
                )
        return Command(
            update={
                "purchase_flow": {**pf, "candidate_track_ids": [int(x) for x in last_track_ids]},
            },
            goto="purchase_interrupt_choose_track",
        )

    # Still no track context: ask user for Track ID or title
    return Command(goto="purchase_interrupt_ask_which")


# Node A2: Interrupt to ask “which track?”
def purchase_interrupt_ask_which(
    state: AppState,
) -> Command[Literal["purchase_resolve_from_free_text", "purchase_done"]]:
    answer = interrupt(
        {
            "type": "input",
            "title": "Purchase Track",
            "text": "Which track would you like to buy? Share a Track ID (e.g. 2269) or a song title.",
            "placeholder": "",
        }
    )
    if not answer:
        return Command(
            update={
                "assistant_messages": add_assistant_message(state, "No problem — cancelled."),
            },
            goto="purchase_done",
        )

    pf = state.get("purchase_flow", {}) or {}
    return Command(
        update={
            "purchase_flow": {
                **pf,
                "query": str(answer),
                "parsed_track_id": _parse_track_id(str(answer)),
                "numeric_ref": _parse_first_int(str(answer)),
            }
        },
        goto="purchase_resolve_from_free_text",
    )


# Node A3: Resolve using free-text query (title search or TrackId)
def purchase_resolve_from_free_text(
    state: AppState,
) -> Command[Literal["purchase_prepare_payment", "purchase_interrupt_choose_track", "purchase_done"]]:
    pf = state.get("purchase_flow", {}) or {}
    user_id = state.get("user_id", 1)
    q = (pf.get("query") or "").strip()
    parsed_track_id = pf.get("parsed_track_id")
    numeric_ref = pf.get("numeric_ref")

    # If we have last_track_ids context and the user typed a number, allow ordinal selection here too.
    last_track_ids = state.get("last_track_ids", []) or []
    if isinstance(last_track_ids, int):
        last_track_ids = [last_track_ids]
    if parsed_track_id is None and isinstance(numeric_ref, int) and last_track_ids:
        if numeric_ref in last_track_ids:
            parsed_track_id = int(numeric_ref)
        elif 1 <= numeric_ref <= len(last_track_ids):
            chosen = int(last_track_ids[numeric_ref - 1])
            return Command(
                update={
                    "purchase_flow": {**pf, "selected_track_id": chosen},
                    "last_track_ids": [chosen],
                },
                goto="purchase_prepare_payment",
            )

    if parsed_track_id:
        track = _fetch_track_by_id(int(parsed_track_id))
        if not track:
            return Command(
                update={
                    "assistant_messages": add_assistant_message(
                        state, f"I couldn’t find Track ID {parsed_track_id}. Try another ID or a title."
                    )
                },
                goto="purchase_done",
            )

        already = check_track_already_purchased(get_engine(), user_id, track["TrackId"])
        if already:
            return Command(
                update={
                    "assistant_messages": add_assistant_message(
                        state,
                        f"You already own \"{track['TrackName']}\" by {track['ArtistName']}. 🎵",
                    ),
                    "last_track_ids": [track["TrackId"]],
                },
                goto="purchase_done",
            )

        return Command(
            update={
                "purchase_flow": {**pf, "selected_track_id": track["TrackId"]},
                "last_track_ids": [track["TrackId"]],
            },
            goto="purchase_prepare_payment",
        )

    # Title search
    results = _search_tracks_by_title(q, limit=5)
    if not results:
        return Command(
            update={
                "assistant_messages": add_assistant_message(
                    state, f"I couldn’t find any tracks matching \"{q}\". Try a different title or a Track ID."
                )
            },
            goto="purchase_done",
        )

    if len(results) == 1:
        track = results[0]
        already = check_track_already_purchased(get_engine(), user_id, track["TrackId"])
        if already:
            return Command(
                update={
                    "assistant_messages": add_assistant_message(
                        state,
                        f"You already own \"{track['TrackName']}\" by {track['ArtistName']}. 🎵",
                    ),
                    "last_track_ids": [track["TrackId"]],
                },
                goto="purchase_done",
            )
        return Command(
            update={
                "purchase_flow": {**pf, "selected_track_id": track["TrackId"]},
                "last_track_ids": [track["TrackId"]],
            },
            goto="purchase_prepare_payment",
        )

    # Multiple: let user choose by index
    return Command(
        update={
            "purchase_flow": {**pf, "candidate_track_ids": [t["TrackId"] for t in results]},
        },
        goto="purchase_interrupt_choose_track",
    )


# Node A4: Interrupt to choose among multiple tracks
def purchase_interrupt_choose_track(
    state: AppState,
) -> Command[Literal["purchase_prepare_payment", "purchase_done"]]:
    pf = state.get("purchase_flow", {}) or {}
    candidate_ids = pf.get("candidate_track_ids", []) or []
    user_id = state.get("user_id", 1)

    # Fetch details for display
    tracks: list[dict] = []
    for tid in candidate_ids[:10]:
        t = _fetch_track_by_id(int(tid))
        if t:
            tracks.append(t)

    if not tracks:
        return Command(
            update={"assistant_messages": add_assistant_message(state, "Sorry — I lost track of the options. Try again.")},
            goto="purchase_done",
        )

    choices = []
    for t in tracks:
        owned = check_track_already_purchased(get_engine(), user_id, t["TrackId"])
        suffix = " (already owned)" if owned else ""
        choices.append(f'{t["TrackName"]} — {t["ArtistName"]} (${t["UnitPrice"]:.2f}) [Track ID: {t["TrackId"]}]{suffix}')

    selection = interrupt(
        {
            "type": "confirm",
            "title": "Choose a Track",
            "text": "Which one would you like to purchase?",
            "choices": choices,
        }
    )

    if not selection:
        return Command(
            update={"assistant_messages": add_assistant_message(state, "No problem — cancelled.")},
            goto="purchase_done",
        )

    # Parse Track ID back out of the chosen label
    chosen_track_id = _parse_track_id(str(selection))
    if not chosen_track_id:
        return Command(
            update={"assistant_messages": add_assistant_message(state, "Sorry — I couldn’t understand that selection.")},
            goto="purchase_done",
        )

    track = _fetch_track_by_id(int(chosen_track_id))
    if not track:
        return Command(
            update={"assistant_messages": add_assistant_message(state, "Sorry — that track is no longer available.")},
            goto="purchase_done",
        )

    # Prevent re-purchase
    if check_track_already_purchased(get_engine(), user_id, track["TrackId"]):
        return Command(
            update={
                "assistant_messages": add_assistant_message(
                    state, f"You already own \"{track['TrackName']}\" by {track['ArtistName']}. 🎵"
                ),
                "last_track_ids": [track["TrackId"]],
            },
            goto="purchase_done",
        )

    return Command(
        update={
            "purchase_flow": {**pf, "selected_track_id": track["TrackId"]},
            "last_track_ids": [track["TrackId"]],
        },
        goto="purchase_prepare_payment",
    )


# Node A5: Prepare payment items for payment_subgraph
def purchase_prepare_payment(state: AppState) -> Command[Literal["payment_flow", "purchase_done"]]:
    pf = state.get("purchase_flow", {}) or {}
    track_id = pf.get("selected_track_id")
    if not track_id:
        return Command(
            update={"assistant_messages": add_assistant_message(state, "Sorry — I couldn’t determine which track to buy.")},
            goto="purchase_done",
        )

    track = _fetch_track_by_id(int(track_id))
    if not track:
        return Command(
            update={"assistant_messages": add_assistant_message(state, "Sorry — that track wasn’t found.")},
            goto="purchase_done",
        )

    items = [
        {
            "track_id": track["TrackId"],
            "name": f'{track["TrackName"]} — {track["ArtistName"]}',
            "qty": 1,
            "unit_price": track["UnitPrice"],
        }
    ]

    # Initialize payment state; payment_subgraph will build_quote + confirm + charge.
    return Command(
        update={
            "payment": {
                "status": "draft",
                "payment_intent_id": "",
                "items": items,
                "total": float(track["UnitPrice"]),
                "transaction_id": "",
                "invoice_id": 0,
                "error": "",
            }
        },
        goto="payment_flow",
    )


# Node A6: Done
def purchase_done(state: AppState) -> dict:
    pf = state.get("purchase_flow", {}) or {}
    return {"purchase_flow": {**pf, "status": "done"}}


def create_purchase_subgraph() -> StateGraph:
    builder = StateGraph(AppState)

    builder.add_node("purchase_init", purchase_init)
    builder.add_node("purchase_resolve_track", purchase_resolve_track)
    builder.add_node("purchase_interrupt_ask_which", purchase_interrupt_ask_which)
    builder.add_node("purchase_resolve_from_free_text", purchase_resolve_from_free_text)
    builder.add_node("purchase_interrupt_choose_track", purchase_interrupt_choose_track)
    builder.add_node("purchase_prepare_payment", purchase_prepare_payment)
    builder.add_node("payment_flow", payment_subgraph)
    builder.add_node("purchase_done", purchase_done)

    builder.set_entry_point("purchase_init")
    builder.add_edge("purchase_init", "purchase_resolve_track")
    builder.add_edge("purchase_done", END)

    # Flow edges controlled by Command returns
    builder.add_edge("purchase_prepare_payment", "payment_flow")
    builder.add_edge("payment_flow", "purchase_done")

    return builder


purchase_subgraph = create_purchase_subgraph().compile()


