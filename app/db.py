"""Database bootstrap for the Chinook music store database.

This module provides utilities to load the Chinook SQLite database,
which contains information about customers, employees, and music sales.
"""

import sqlite3
import requests
from sqlalchemy import create_engine, Engine
from sqlalchemy.pool import StaticPool
from langchain_community.utilities.sql_database import SQLDatabase


# URL for the Chinook SQL script
CHINOOK_SQL_URL = "https://raw.githubusercontent.com/lerocha/chinook-database/master/ChinookDatabase/DataSources/Chinook_Sqlite.sql"


def get_engine_for_chinook_db() -> Engine:
    """Pull SQL file, populate in-memory database, and create engine.
    
    Downloads the Chinook database SQL script from GitHub and creates
    an in-memory SQLite database with the schema and data.
    
    Returns:
        SQLAlchemy Engine connected to the in-memory Chinook database.
    """
    response = requests.get(CHINOOK_SQL_URL)
    response.raise_for_status()
    sql_script = response.text

    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.executescript(sql_script)
    
    # Update demo user (Customer ID 1) with real phone for Twilio verification
    connection.execute(
        "UPDATE Customer SET Phone = ? WHERE CustomerId = 1",
        ("+19144342859",)
    )
    connection.commit()
    
    return create_engine(
        "sqlite://",
        creator=lambda: connection,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


def get_sql_database(engine: Engine) -> SQLDatabase:
    """Create a LangChain SQLDatabase wrapper from an engine.
    
    Args:
        engine: SQLAlchemy Engine to wrap.
        
    Returns:
        LangChain SQLDatabase instance.
    """
    return SQLDatabase(engine)


# Module-level engine and database instances (lazy initialization)
_engine: Engine | None = None
_db: SQLDatabase | None = None


def get_engine() -> Engine:
    """Get or create the global database engine.
    
    Returns:
        SQLAlchemy Engine for the Chinook database.
    """
    global _engine
    if _engine is None:
        _engine = get_engine_for_chinook_db()
    return _engine


def get_db() -> SQLDatabase:
    """Get or create the global SQLDatabase instance.
    
    Returns:
        LangChain SQLDatabase for the Chinook database.
    """
    global _db
    if _db is None:
        _db = get_sql_database(get_engine())
    return _db


def get_table_names() -> list[str]:
    """Get list of available tables in the database.
    
    Returns:
        List of table names.
    """
    return get_db().get_usable_table_names()

