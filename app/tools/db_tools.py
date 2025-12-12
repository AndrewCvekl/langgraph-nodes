"""Safe database tools using parameterized SQL queries.

All functions in this module use SQLAlchemy's text() with parameter binding
to prevent SQL injection. No f-string interpolation of user input is used.
"""

from typing import Optional
from sqlalchemy import text, Engine
from datetime import datetime


def get_customer_contact(engine: Engine, customer_id: int) -> dict:
    """Look up customer contact info (email and phone).
    
    Args:
        engine: SQLAlchemy database engine.
        customer_id: Customer ID to look up.
        
    Returns:
        Dict with Email and Phone keys.
        
    Raises:
        ValueError: If customer not found.
    """
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT Email, Phone FROM Customer WHERE CustomerId = :id"),
            {"id": customer_id}
        ).fetchone()
    
    if result is None:
        raise ValueError(f"Customer with ID {customer_id} not found")
    
    return {"Email": result[0], "Phone": result[1]}


def update_customer_email(engine: Engine, customer_id: int, new_email: str) -> None:
    """Update a customer's email address.
    
    Args:
        engine: SQLAlchemy database engine.
        customer_id: Customer ID to update.
        new_email: New email address.
        
    Raises:
        ValueError: If customer not found.
    """
    with engine.connect() as conn:
        result = conn.execute(
            text("UPDATE Customer SET Email = :email WHERE CustomerId = :id"),
            {"email": new_email, "id": customer_id}
        )
        conn.commit()
        
        if result.rowcount == 0:
            raise ValueError(f"Customer with ID {customer_id} not found")


def find_track_by_title_artist(
    engine: Engine,
    title: str,
    artist: str
) -> Optional[dict]:
    """Find a track in the catalogue by title and artist.
    
    Args:
        engine: SQLAlchemy database engine.
        title: Track title (partial match).
        artist: Artist name (partial match).
        
    Returns:
        Dict with track info or None if not found.
        Keys: TrackId, TrackName, UnitPrice, AlbumTitle, ArtistName
    """
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 
                    Track.TrackId,
                    Track.Name AS TrackName,
                    Track.UnitPrice,
                    Album.Title AS AlbumTitle,
                    Artist.Name AS ArtistName
                FROM Track
                JOIN Album ON Track.AlbumId = Album.AlbumId
                JOIN Artist ON Album.ArtistId = Artist.ArtistId
                WHERE Track.Name LIKE :title
                  AND Artist.Name LIKE :artist
                LIMIT 1
            """),
            {"title": f"%{title}%", "artist": f"%{artist}%"}
        ).fetchone()
    
    if result is None:
        return None
    
    return {
        "TrackId": result[0],
        "TrackName": result[1],
        "UnitPrice": float(result[2]),
        "AlbumTitle": result[3],
        "ArtistName": result[4],
    }


def create_invoice_for_track(
    engine: Engine,
    customer_id: int,
    track_id: int,
    unit_price: float,
    qty: int = 1
) -> dict:
    """Create an invoice and invoice line for a track purchase.
    
    Args:
        engine: SQLAlchemy database engine.
        customer_id: Customer making the purchase.
        track_id: Track being purchased.
        unit_price: Price per unit.
        qty: Quantity (default 1).
        
    Returns:
        Dict with invoice_id, total, and lines.
    """
    total = unit_price * qty
    invoice_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with engine.connect() as conn:
        # Get customer billing info
        customer = conn.execute(
            text("""
                SELECT Address, City, State, Country, PostalCode
                FROM Customer
                WHERE CustomerId = :id
            """),
            {"id": customer_id}
        ).fetchone()
        
        if customer is None:
            raise ValueError(f"Customer with ID {customer_id} not found")
        
        # Create invoice
        result = conn.execute(
            text("""
                INSERT INTO Invoice (
                    CustomerId, InvoiceDate, 
                    BillingAddress, BillingCity, BillingState, 
                    BillingCountry, BillingPostalCode, Total
                )
                VALUES (
                    :customer_id, :invoice_date,
                    :address, :city, :state,
                    :country, :postal_code, :total
                )
            """),
            {
                "customer_id": customer_id,
                "invoice_date": invoice_date,
                "address": customer[0],
                "city": customer[1],
                "state": customer[2],
                "country": customer[3],
                "postal_code": customer[4],
                "total": total,
            }
        )
        invoice_id = result.lastrowid
        
        # Create invoice line
        conn.execute(
            text("""
                INSERT INTO InvoiceLine (
                    InvoiceId, TrackId, UnitPrice, Quantity
                )
                VALUES (
                    :invoice_id, :track_id, :unit_price, :qty
                )
            """),
            {
                "invoice_id": invoice_id,
                "track_id": track_id,
                "unit_price": unit_price,
                "qty": qty,
            }
        )
        
        conn.commit()
    
    return {
        "invoice_id": invoice_id,
        "total": total,
        "lines": [
            {
                "track_id": track_id,
                "unit_price": unit_price,
                "quantity": qty,
            }
        ],
    }


def get_albums_by_artist(engine: Engine, artist_substr: str) -> list[dict]:
    """Get albums by an artist (partial name match).
    
    Args:
        engine: SQLAlchemy database engine.
        artist_substr: Artist name substring to search.
        
    Returns:
        List of dicts with Title and ArtistName keys.
    """
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT Album.Title, Artist.Name
                FROM Album
                JOIN Artist ON Album.ArtistId = Artist.ArtistId
                WHERE Artist.Name LIKE :artist
                ORDER BY Album.Title
                LIMIT 20
            """),
            {"artist": f"%{artist_substr}%"}
        ).fetchall()
    
    return [{"Title": r[0], "ArtistName": r[1]} for r in results]


def get_tracks_by_artist(engine: Engine, artist_substr: str) -> list[dict]:
    """Get tracks by an artist (partial name match).
    
    Args:
        engine: SQLAlchemy database engine.
        artist_substr: Artist name substring to search.
        
    Returns:
        List of dicts with TrackName, ArtistName, AlbumTitle, UnitPrice keys.
    """
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT 
                    Track.Name AS TrackName,
                    Artist.Name AS ArtistName,
                    Album.Title AS AlbumTitle,
                    Track.UnitPrice
                FROM Track
                JOIN Album ON Track.AlbumId = Album.AlbumId
                JOIN Artist ON Album.ArtistId = Artist.ArtistId
                WHERE Artist.Name LIKE :artist
                ORDER BY Track.Name
                LIMIT 50
            """),
            {"artist": f"%{artist_substr}%"}
        ).fetchall()
    
    return [
        {
            "TrackName": r[0],
            "ArtistName": r[1],
            "AlbumTitle": r[2],
            "UnitPrice": float(r[3]),
        }
        for r in results
    ]


def check_for_songs(engine: Engine, title_substr: str) -> list[dict]:
    """Check if songs exist by title (partial match).
    
    Args:
        engine: SQLAlchemy database engine.
        title_substr: Song title substring to search.
        
    Returns:
        List of dicts with track info.
    """
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
                WHERE Track.Name LIKE :title
                ORDER BY Track.Name
                LIMIT 20
            """),
            {"title": f"%{title_substr}%"}
        ).fetchall()
    
    return [
        {
            "TrackId": r[0],
            "TrackName": r[1],
            "ArtistName": r[2],
            "AlbumTitle": r[3],
            "UnitPrice": float(r[4]),
        }
        for r in results
    ]


def get_customer_info(engine: Engine, customer_id: int) -> dict:
    """Get full customer information.
    
    Args:
        engine: SQLAlchemy database engine.
        customer_id: Customer ID to look up.
        
    Returns:
        Dict with all customer fields.
        
    Raises:
        ValueError: If customer not found.
    """
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT 
                    CustomerId, FirstName, LastName, Company,
                    Address, City, State, Country, PostalCode,
                    Phone, Fax, Email
                FROM Customer
                WHERE CustomerId = :id
            """),
            {"id": customer_id}
        ).fetchone()
    
    if result is None:
        raise ValueError(f"Customer with ID {customer_id} not found")
    
    return {
        "CustomerId": result[0],
        "FirstName": result[1],
        "LastName": result[2],
        "Company": result[3],
        "Address": result[4],
        "City": result[5],
        "State": result[6],
        "Country": result[7],
        "PostalCode": result[8],
        "Phone": result[9],
        "Fax": result[10],
        "Email": result[11],
    }


def get_customer_invoices(engine: Engine, customer_id: int) -> list[dict]:
    """Get all invoices for a customer.
    
    Args:
        engine: SQLAlchemy database engine.
        customer_id: Customer ID.
        
    Returns:
        List of invoice dicts.
    """
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT 
                    InvoiceId, InvoiceDate, Total
                FROM Invoice
                WHERE CustomerId = :id
                ORDER BY InvoiceDate DESC
                LIMIT 20
            """),
            {"id": customer_id}
        ).fetchall()
    
    return [
        {
            "InvoiceId": r[0],
            "InvoiceDate": r[1],
            "Total": float(r[2]),
        }
        for r in results
    ]


def check_track_already_purchased(
    engine: Engine,
    customer_id: int,
    track_id: int
) -> bool:
    """Check if a customer has already purchased a specific track.
    
    Args:
        engine: SQLAlchemy database engine.
        customer_id: Customer ID.
        track_id: Track ID to check.
        
    Returns:
        True if the customer has already purchased this track, False otherwise.
    """
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT COUNT(*) 
                FROM InvoiceLine
                JOIN Invoice ON InvoiceLine.InvoiceId = Invoice.InvoiceId
                WHERE Invoice.CustomerId = :customer_id
                  AND InvoiceLine.TrackId = :track_id
            """),
            {"customer_id": customer_id, "track_id": track_id}
        ).fetchone()
    
    return result[0] > 0 if result else False


def get_all_genres(engine: Engine) -> list[dict]:
    """Get all available genres in the catalogue.
    
    Args:
        engine: SQLAlchemy database engine.
        
    Returns:
        List of dicts with GenreName keys.
    """
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT DISTINCT Genre.Name AS GenreName
                FROM Genre
                JOIN Track ON Genre.GenreId = Track.GenreId
                ORDER BY Genre.Name
            """)
        ).fetchall()
    
    return [{"GenreName": r[0]} for r in results]


def get_artists_by_genre(engine: Engine, genre_substr: str) -> list[dict]:
    """Get artists that have tracks in a specific genre (partial genre name match).
    
    Args:
        engine: SQLAlchemy database engine.
        genre_substr: Genre name substring to search (e.g., "pop", "rock").
        
    Returns:
        List of dicts with ArtistName and GenreName keys.
    """
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT DISTINCT 
                    Artist.Name AS ArtistName,
                    Genre.Name AS GenreName
                FROM Artist
                JOIN Album ON Artist.ArtistId = Album.ArtistId
                JOIN Track ON Album.AlbumId = Track.AlbumId
                JOIN Genre ON Track.GenreId = Genre.GenreId
                WHERE Genre.Name LIKE :genre
                ORDER BY Artist.Name
                LIMIT 50
            """),
            {"genre": f"%{genre_substr}%"}
        ).fetchall()
    
    return [
        {
            "ArtistName": r[0],
            "GenreName": r[1],
        }
        for r in results
    ]


def get_albums_by_genre(engine: Engine, genre_substr: str) -> list[dict]:
    """Get albums that have tracks in a specific genre (partial genre name match).
    
    Args:
        engine: SQLAlchemy database engine.
        genre_substr: Genre name substring to search (e.g., "pop", "rock").
        
    Returns:
        List of dicts with AlbumTitle, ArtistName, and GenreName keys.
    """
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT DISTINCT 
                    Album.Title AS AlbumTitle,
                    Artist.Name AS ArtistName,
                    Genre.Name AS GenreName
                FROM Album
                JOIN Artist ON Album.ArtistId = Artist.ArtistId
                JOIN Track ON Album.AlbumId = Track.AlbumId
                JOIN Genre ON Track.GenreId = Genre.GenreId
                WHERE Genre.Name LIKE :genre
                ORDER BY Album.Title
                LIMIT 50
            """),
            {"genre": f"%{genre_substr}%"}
        ).fetchall()
    
    return [
        {
            "AlbumTitle": r[0],
            "ArtistName": r[1],
            "GenreName": r[2],
        }
        for r in results
    ]


def get_tracks_by_genre(engine: Engine, genre_substr: str) -> list[dict]:
    """Get tracks in a specific genre (partial genre name match).
    
    Args:
        engine: SQLAlchemy database engine.
        genre_substr: Genre name substring to search (e.g., "pop", "rock").
        
    Returns:
        List of dicts with TrackName, ArtistName, AlbumTitle, GenreName, and UnitPrice keys.
    """
    with engine.connect() as conn:
        results = conn.execute(
            text("""
                SELECT 
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
                LIMIT 50
            """),
            {"genre": f"%{genre_substr}%"}
        ).fetchall()
    
    return [
        {
            "TrackName": r[0],
            "ArtistName": r[1],
            "AlbumTitle": r[2],
            "GenreName": r[3],
            "UnitPrice": float(r[4]),
        }
        for r in results
    ]


def search_artists(engine: Engine, artist_substr: str = "") -> list[dict]:
    """Search for artists by name (partial match). If empty string, returns all artists (limited).
    
    Args:
        engine: SQLAlchemy database engine.
        artist_substr: Artist name substring to search. Empty string returns all artists.
        
    Returns:
        List of dicts with ArtistName keys.
    """
    with engine.connect() as conn:
        if artist_substr:
            results = conn.execute(
                text("""
                    SELECT DISTINCT Artist.Name AS ArtistName
                    FROM Artist
                    JOIN Album ON Artist.ArtistId = Album.ArtistId
                    WHERE Artist.Name LIKE :artist
                    ORDER BY Artist.Name
                    LIMIT 100
                """),
                {"artist": f"%{artist_substr}%"}
            ).fetchall()
        else:
            results = conn.execute(
                text("""
                    SELECT DISTINCT Artist.Name AS ArtistName
                    FROM Artist
                    JOIN Album ON Artist.ArtistId = Album.ArtistId
                    ORDER BY Artist.Name
                    LIMIT 100
                """)
            ).fetchall()
    
    return [{"ArtistName": r[0]} for r in results]


def search_albums(engine: Engine, album_substr: str = "") -> list[dict]:
    """Search for albums by title (partial match). If empty string, returns all albums (limited).

    Args:
        engine: SQLAlchemy database engine.
        album_substr: Album title substring to search. Empty string returns all albums.

    Returns:
        List of dicts with AlbumTitle and ArtistName keys.
    """
    with engine.connect() as conn:
        if album_substr:
            results = conn.execute(
                text("""
                    SELECT DISTINCT
                        Album.Title AS AlbumTitle,
                        Artist.Name AS ArtistName
                    FROM Album
                    JOIN Artist ON Album.ArtistId = Artist.ArtistId
                    WHERE Album.Title LIKE :album
                    ORDER BY Album.Title
                    LIMIT 100
                """),
                {"album": f"%{album_substr}%"}
            ).fetchall()
        else:
            results = conn.execute(
                text("""
                    SELECT DISTINCT
                        Album.Title AS AlbumTitle,
                        Artist.Name AS ArtistName
                    FROM Album
                    JOIN Artist ON Album.ArtistId = Artist.ArtistId
                    ORDER BY Album.Title
                    LIMIT 100
                """)
            ).fetchall()

    return [
        {
            "AlbumTitle": r[0],
            "ArtistName": r[1],
        }
        for r in results
    ]


def get_invoice_details(engine: Engine, customer_id: int, invoice_id: int) -> dict:
    """Get detailed information for a specific invoice.
    
    Args:
        engine: SQLAlchemy database engine.
        customer_id: Customer ID (for security - ensures customer owns the invoice).
        invoice_id: Invoice ID to retrieve.
        
    Returns:
        Dict with invoice header and line items.
        Keys: InvoiceId, InvoiceDate, Total, BillingAddress, BillingCity, 
              BillingState, BillingCountry, BillingPostalCode, Items (list)
        
    Raises:
        ValueError: If invoice not found or doesn't belong to customer.
    """
    with engine.connect() as conn:
        # Get invoice header
        invoice_result = conn.execute(
            text("""
                SELECT 
                    InvoiceId, CustomerId, InvoiceDate, Total,
                    BillingAddress, BillingCity, BillingState,
                    BillingCountry, BillingPostalCode
                FROM Invoice
                WHERE InvoiceId = :invoice_id AND CustomerId = :customer_id
            """),
            {"invoice_id": invoice_id, "customer_id": customer_id}
        ).fetchone()
        
        if invoice_result is None:
            raise ValueError(
                f"Invoice #{invoice_id} not found or does not belong to customer"
            )
        
        # Get invoice line items
        items_result = conn.execute(
            text("""
                SELECT 
                    Track.Name AS TrackName,
                    Artist.Name AS ArtistName,
                    Album.Title AS AlbumTitle,
                    InvoiceLine.UnitPrice,
                    InvoiceLine.Quantity
                FROM InvoiceLine
                JOIN Track ON InvoiceLine.TrackId = Track.TrackId
                JOIN Album ON Track.AlbumId = Album.AlbumId
                JOIN Artist ON Album.ArtistId = Artist.ArtistId
                WHERE InvoiceLine.InvoiceId = :invoice_id
                ORDER BY InvoiceLine.InvoiceLineId
            """),
            {"invoice_id": invoice_id}
        ).fetchall()
        
        items = [
            {
                "TrackName": item[0],
                "ArtistName": item[1],
                "AlbumTitle": item[2],
                "UnitPrice": float(item[3]),
                "Quantity": item[4],
            }
            for item in items_result
        ]
        
        return {
            "InvoiceId": invoice_result[0],
            "CustomerId": invoice_result[1],
            "InvoiceDate": invoice_result[2],
            "Total": float(invoice_result[3]),
            "BillingAddress": invoice_result[4],
            "BillingCity": invoice_result[5],
            "BillingState": invoice_result[6],
            "BillingCountry": invoice_result[7],
            "BillingPostalCode": invoice_result[8],
            "Items": items,
        }

