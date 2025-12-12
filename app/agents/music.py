"""Music agent for handling catalogue queries.

Handles questions about albums, artists, and tracks in the music store.
"""

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, SystemMessage, AIMessage
from langchain_core.tools import tool

from app.config import config
from app.db import get_engine
from app.tools.db_tools import (
    get_albums_by_artist,
    get_tracks_by_artist,
    check_for_songs,
    get_all_genres,
    get_artists_by_genre,
    get_albums_by_genre,
    get_tracks_by_genre,
    search_artists,
    search_albums,
    create_invoice_for_track,
)
from app.tools.youtube_mock import get_youtube
from app.tools.payment_mock import get_payment


MUSIC_SYSTEM_PROMPT = """You are a helpful music store assistant. Your job is to help customers find music in our catalogue.

CRITICAL RULE: You MUST ALWAYS query the database using your tools before answering ANY question about music. 
NEVER provide generic answers or information not from our database. ALL answers must be grounded in actual data from our catalogue.

You have access to tools to search our music database:
- get_genres: Get all available genres in our catalogue
- get_artists_in_genre: Find artists that have tracks in a specific genre (e.g., "pop", "rock")
- get_albums_in_genre: Find albums that have tracks in a specific genre
- get_songs_in_genre: Find tracks/songs in a specific genre
- search_all_artists: Search for artists by name (or get all artists if empty string)
- search_all_albums: Search for albums by title (or get all albums if empty string)
- search_albums_by_artist: Find albums by a specific artist name
- search_tracks_by_artist: Find individual tracks/songs by an artist name
- search_songs_by_title: Search for songs by title
- search_song_video: Find a YouTube video for a song (official audio/video)
- purchase_song: Purchase a song from the catalogue (requires track_id)

When a customer asks about music:
1. ALWAYS use the appropriate tool(s) to search our catalogue FIRST
2. Present ONLY the results from the database in a friendly, helpful way
3. If nothing is found, let them know politely based on the actual database results
4. NEVER make up or guess information - only use what the tools return

Examples of questions you MUST query the database for:
- "What genres do you have?" → Use get_genres
- "What pop artists do you have?" → Use get_artists_in_genre("pop")
- "What albums are in rock?" → Use get_albums_in_genre("rock")
- "What songs are pop?" → Use get_songs_in_genre("pop")
- "What artists do you have?" → Use search_all_artists("")
- "What albums do you have?" → Use search_all_albums("")
- "What albums by Queen?" → Use search_albums_by_artist("Queen")
- "What songs by The Beatles?" → Use search_tracks_by_artist("Beatles")
- "Can I watch the video for <song/artist>?" → Use search_song_video("<song> <artist> official video")
- "I want to buy <song>" or "Buy <song>" → First use search_songs_by_title to find the track_id, then use purchase_song with the track_id
- "Can I buy this song?" or "Can I buy <song>?" → Identify which song they're referring to, then ASK for confirmation before purchasing. Do NOT purchase immediately - wait for explicit confirmation like "yes", "buy it", "purchase it". Present a clear Yes/No choice like: "Would you like me to purchase <song> for $X.XX? (Yes/No)"

Be conversational and helpful. Format results nicely when presenting them to customers.

IMPORTANT PURCHASE RULES:
- NEVER use purchase_song unless the customer has EXPLICITLY confirmed they want to buy (e.g., "yes", "buy it", "purchase it", "I want to buy it")
- If a customer asks "can I buy this song?" or "can I buy <song>?", identify the song and ask: "Would you like me to purchase [song name] for $X.XX? (Yes/No)"
- Only proceed with purchase_song after receiving explicit confirmation
- If the customer is just asking about purchasing (questions like "can I buy", "how much is", "is it available"), provide information but do NOT purchase

OTHER IMPORTANT RULES:
- If a customer just says "hi", "hello", or "hey" (simple greetings), respond with a friendly greeting and ask how you can help them find music
- Do NOT try to search for "hi", "hello", or "hey" as song titles - these are greetings, not music queries
- Only use your tools when the customer is actually asking about music (artists, albums, songs, genres, etc.)
- For email updates or lyrics identification, the customer will be routed to a different assistant
- REMEMBER: Always query the database - never give generic answers about music"""


@tool
def search_albums_by_artist(artist_name: str) -> str:
    """Search for albums by an artist name.
    
    Args:
        artist_name: The artist name to search for (partial match supported).
        
    Returns:
        Formatted string of matching albums.
    """
    engine = get_engine()
    albums = get_albums_by_artist(engine, artist_name)
    
    if not albums:
        return f"No albums found for artist matching '{artist_name}'."
    
    result = f"Found {len(albums)} album(s):\n"
    for album in albums:
        result += f"- {album['Title']} by {album['ArtistName']}\n"
    
    return result


@tool
def search_tracks_by_artist(artist_name: str) -> str:
    """Search for tracks/songs by an artist name.
    
    Args:
        artist_name: The artist name to search for (partial match supported).
        
    Returns:
        Formatted string of matching tracks with track IDs for purchase.
    """
    engine = get_engine()
    tracks = get_tracks_by_artist(engine, artist_name)
    
    if not tracks:
        return f"No tracks found for artist matching '{artist_name}'."
    
    # Need to get track IDs - let's query directly
    from sqlalchemy import text
    
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT 
                    Track.TrackId,
                    Track.Name AS TrackName,
                    Artist.Name AS ArtistName,
                    Album.Title AS AlbumTitle,
                    Track.UnitPrice
                FROM Track
                JOIN Album ON Track.AlbumId = Album.AlbumId
                JOIN Artist ON Album.ArtistId = Artist.ArtistId
                WHERE Artist.Name LIKE :artist
                ORDER BY Track.Name
                LIMIT 10
            """),
            {"artist": f"%{artist_name}%"}
        ).fetchall()
    
    result = f"Found {len(tracks)} track(s):\n"
    for r in results:
        track_id = r[0]
        track_name = r[1]
        album_title = r[3]
        unit_price = float(r[4])
        result += f"- {track_name} from '{album_title}' (${unit_price:.2f}) [Track ID: {track_id}]\n"
    
    if len(tracks) > 10:
        result += f"... and {len(tracks) - 10} more tracks.\n"
    
    return result


@tool
def search_songs_by_title(song_title: str) -> str:
    """Search for songs by title.
    
    Args:
        song_title: The song title to search for (partial match supported).
        
    Returns:
        Formatted string of matching songs with track IDs for purchase.
    """
    engine = get_engine()
    songs = check_for_songs(engine, song_title)
    
    if not songs:
        return f"No songs found matching '{song_title}'."
    
    result = f"Found {len(songs)} song(s):\n"
    for song in songs:
        result += f"- {song['TrackName']} by {song['ArtistName']} (${song['UnitPrice']:.2f}) [Track ID: {song['TrackId']}]\n"
    
    return result


@tool
def search_song_video(query: str) -> str:
    """Find a YouTube video for a song (mocked if API key not set).
    
    Args:
        query: Song/artist query, e.g., "Song Name Artist official video".
        
    Returns:
        Formatted string with video title and URL.
    """
    youtube = get_youtube()
    video = youtube.search_video(query)
    title = video.get("title", "Unknown Video")
    url = video.get("url", "https://www.youtube.com")
    channel = video.get("channel", "Unknown")
    return f"Found a video: '{title}' by {channel}\nWatch here: {url}"


def make_purchase_tool(user_id: int):
    """Create a purchase tool bound to a specific user ID.
    
    Args:
        user_id: The authenticated user's ID.
        
    Returns:
        Purchase tool function.
    """
    @tool
    def purchase_song(track_id: int) -> str:
        """Purchase a song from the catalogue.
        
        IMPORTANT: Only use this tool when the customer has EXPLICITLY confirmed they want to purchase 
        (e.g., "yes", "buy it", "purchase it", "I want to buy it"). Do NOT use for questions like 
        "can I buy this song?" - those require confirmation first.
        
        Args:
            track_id: The track ID to purchase (get this from search results).
            
        Returns:
            Confirmation message with invoice details.
        """
        from sqlalchemy import text
        
        engine = get_engine()
        payment_service = get_payment()
        
        # Get track info directly from database
        with engine.connect() as conn:
            result = conn.execute(
                text("""
                    SELECT 
                        Track.TrackId,
                        Track.Name AS TrackName,
                        Track.UnitPrice,
                        Artist.Name AS ArtistName
                    FROM Track
                    JOIN Album ON Track.AlbumId = Album.AlbumId
                    JOIN Artist ON Album.ArtistId = Artist.ArtistId
                    WHERE Track.TrackId = :track_id
                """),
                {"track_id": track_id}
            ).fetchone()
        
        if not result:
            return f"Error: Track with ID {track_id} not found in our catalogue."
        
        track_name = result[1]
        unit_price = float(result[2])
        artist_name = result[3]
        
        # Create payment intent
        items = [{
            "track_id": track_id,
            "name": track_name,
            "qty": 1,
            "unit_price": unit_price,
        }]
        intent_id = payment_service.create_payment_intent(unit_price, user_id, items)
        
        # Process payment
        result = payment_service.charge(intent_id, unit_price, user_id, items)
        
        if result.get("status") != "succeeded":
            return f"Sorry, payment failed: {result.get('reason', 'Unknown error')}. Please try again."
        
        # Create invoice in database
        try:
            invoice_result = create_invoice_for_track(
                engine,
                customer_id=user_id,
                track_id=track_id,
                unit_price=unit_price,
                qty=1,
            )
            invoice_id = invoice_result.get("invoice_id", 0)
            transaction_id = result.get("transaction_id", "")
            
            return (
                f"Purchase successful! 🎵\n\n"
                f"Song: {track_name} by {artist_name}\n"
                f"Price: ${unit_price:.2f}\n"
                f"Invoice #: {invoice_id}\n"
                f"Transaction ID: {transaction_id}\n\n"
                f"Thank you for your purchase!"
            )
        except Exception as e:
            # Payment succeeded but invoice creation failed
            transaction_id = result.get("transaction_id", "")
            return (
                f"Payment processed successfully (Transaction: {transaction_id}), "
                f"but there was an issue creating the invoice. Please contact support."
            )
    
    return purchase_song


@tool
def get_genres() -> str:
    """Get all available genres in the catalogue.
    
    Returns:
        Formatted string of all genres.
    """
    engine = get_engine()
    genres = get_all_genres(engine)
    
    if not genres:
        return "No genres found in the catalogue."
    
    result = f"Found {len(genres)} genre(s):\n"
    for genre in genres:
        result += f"- {genre['GenreName']}\n"
    
    return result


@tool
def get_artists_in_genre(genre_name: str) -> str:
    """Get artists that have tracks in a specific genre.
    
    Args:
        genre_name: The genre name to search for (partial match supported, e.g., "pop", "rock").
        
    Returns:
        Formatted string of matching artists.
    """
    engine = get_engine()
    artists = get_artists_by_genre(engine, genre_name)
    
    if not artists:
        return f"No artists found with tracks in genre matching '{genre_name}'."
    
    result = f"Found {len(artists)} artist(s) with tracks in genre(s) matching '{genre_name}':\n"
    for artist in artists[:30]:  # Limit display
        result += f"- {artist['ArtistName']} (genre: {artist['GenreName']})\n"
    
    if len(artists) > 30:
        result += f"... and {len(artists) - 30} more artists.\n"
    
    return result


@tool
def get_albums_in_genre(genre_name: str) -> str:
    """Get albums that have tracks in a specific genre.
    
    Args:
        genre_name: The genre name to search for (partial match supported, e.g., "pop", "rock").
        
    Returns:
        Formatted string of matching albums.
    """
    engine = get_engine()
    albums = get_albums_by_genre(engine, genre_name)
    
    if not albums:
        return f"No albums found with tracks in genre matching '{genre_name}'."
    
    result = f"Found {len(albums)} album(s) with tracks in genre matching '{genre_name}':\n"
    for album in albums[:30]:  # Limit display
        result += f"- {album['AlbumTitle']} by {album['ArtistName']} (genre: {album['GenreName']})\n"
    
    if len(albums) > 30:
        result += f"... and {len(albums) - 30} more albums.\n"
    
    return result


@tool
def get_songs_in_genre(genre_name: str) -> str:
    """Get songs/tracks in a specific genre.
    
    Args:
        genre_name: The genre name to search for (partial match supported, e.g., "pop", "rock").
        
    Returns:
        Formatted string of matching songs with track IDs for purchase.
    """
    from sqlalchemy import text
    
    engine = get_engine()
    
    # Query directly to get track IDs
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT 
                    Track.TrackId,
                    Track.Name AS TrackName,
                    Artist.Name AS ArtistName,
                    Album.Title AS AlbumTitle,
                    Genre.Name AS GenreName,
                    Track.UnitPrice
                FROM Track
                JOIN Album ON Track.AlbumId = Album.AlbumId
                JOIN Artist ON Album.ArtistId = Artist.ArtistId
                JOIN Genre ON Track.GenreId = Genre.GenreId
                WHERE Genre.Name LIKE :genre
                ORDER BY Track.Name
                LIMIT 30
            """),
            {"genre": f"%{genre_name}%"}
        ).fetchall()
        
        # Check if there are more
        count_result = conn.execute(
            text("""
                SELECT COUNT(*) 
                FROM Track
                JOIN Genre ON Track.GenreId = Genre.GenreId
                WHERE Genre.Name LIKE :genre
            """),
            {"genre": f"%{genre_name}%"}
        ).fetchone()
    
    if not results:
        return f"No songs found in genre matching '{genre_name}'."
    
    result = f"Found {len(results)} song(s) in genre matching '{genre_name}':\n"
    for r in results:
        track_id = r[0]
        track_name = r[1]
        artist_name = r[2]
        album_title = r[3]
        unit_price = float(r[5])
        result += f"- {track_name} by {artist_name} from '{album_title}' (${unit_price:.2f}) [Track ID: {track_id}]\n"
    
    total_count = count_result[0] if count_result else len(results)
    if total_count > 30:
        result += f"... and {total_count - 30} more songs.\n"
    
    return result


@tool
def search_all_artists(artist_name: str = "") -> str:
    """Search for artists by name, or get all artists if no name provided.
    
    Args:
        artist_name: Optional artist name to search for (partial match). If empty, returns all artists.
        
    Returns:
        Formatted string of matching artists.
    """
    engine = get_engine()
    artists = search_artists(engine, artist_name)
    
    if not artists:
        if artist_name:
            return f"No artists found matching '{artist_name}'."
        else:
            return "No artists found in the catalogue."
    
    if artist_name:
        result = f"Found {len(artists)} artist(s) matching '{artist_name}':\n"
    else:
        result = f"Found {len(artists)} artist(s) in our catalogue:\n"
    
    for artist in artists[:50]:  # Limit display
        result += f"- {artist['ArtistName']}\n"
    
    if len(artists) > 50:
        result += f"... and {len(artists) - 50} more artists.\n"
    
    return result


@tool
def search_all_albums(album_title: str = "") -> str:
    """Search for albums by title, or get all albums if no title provided.
    
    Args:
        album_title: Optional album title to search for (partial match). If empty, returns all albums.
        
    Returns:
        Formatted string of matching albums.
    """
    engine = get_engine()
    albums = search_albums(engine, album_title)
    
    if not albums:
        if album_title:
            return f"No albums found matching '{album_title}'."
        else:
            return "No albums found in the catalogue."
    
    if album_title:
        result = f"Found {len(albums)} album(s) matching '{album_title}':\n"
    else:
        result = f"Found {len(albums)} album(s) in our catalogue:\n"
    
    for album in albums[:50]:  # Limit display
        result += f"- {album['AlbumTitle']} by {album['ArtistName']}\n"
    
    if len(albums) > 50:
        result += f"... and {len(albums) - 50} more albums.\n"
    
    return result


def get_music_model() -> ChatOpenAI:
    """Get the LLM configured for music queries."""
    return ChatOpenAI(
        model=config.OPENAI_MODEL,
        temperature=0.3,
        streaming=True,
    )


def music_agent(messages: list[BaseMessage], user_id: int = 1) -> AIMessage:
    """Run the music agent to answer catalogue queries.
    
    Args:
        messages: Conversation messages.
        user_id: The authenticated user's ID (defaults to 1).
        
    Returns:
        AI response message.
    """
    model = get_music_model()
    purchase_tool = make_purchase_tool(user_id)
    tools = [
        get_genres,
        get_artists_in_genre,
        get_albums_in_genre,
        get_songs_in_genre,
        search_all_artists,
        search_all_albums,
        search_albums_by_artist,
        search_tracks_by_artist,
        search_songs_by_title,
        search_song_video,
        purchase_tool,
    ]
    model_with_tools = model.bind_tools(tools)
    
    # Prepend system prompt
    full_messages = [SystemMessage(content=MUSIC_SYSTEM_PROMPT)] + messages
    
    tools_by_name = {t.name: t for t in tools}
    max_iterations = 5  # Prevent infinite loops
    
    # Handle multiple rounds of tool calls if needed
    for iteration in range(max_iterations):
        # Always use model with tools so it can make tool calls in any iteration
        response = model_with_tools.invoke(full_messages)
        
        # If no tool calls, we're done
        if not response.tool_calls:
            break
        
        # Execute tool calls
        tool_messages = []
        for tool_call in response.tool_calls:
            tool_fn = tools_by_name.get(tool_call["name"])
            if tool_fn:
                from langchain_core.messages import ToolMessage
                result = tool_fn.invoke(tool_call["args"])
                tool_messages.append(
                    ToolMessage(content=result, tool_call_id=tool_call["id"])
                )
        
        # Add tool results to conversation
        full_messages = full_messages + [response] + tool_messages
    
    # If we still have tool calls after max iterations, get final response without tools
    if response.tool_calls:
        response = model.invoke(full_messages)
    
    return response

