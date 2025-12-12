"""Configuration and environment settings."""

import os
from dotenv import load_dotenv

# Load .env file from project root (relative to this file)
# This file is at: app/config.py
# Project root is: ../
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
env_path = os.path.join(project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path, override=False)  # Don't override if already set
else:
    # Fallback: try find_dotenv() which searches upward from current directory
    from dotenv import find_dotenv
    found = find_dotenv()
    if found:
        load_dotenv(found, override=False)
    else:
        load_dotenv()  # Current directory as last resort


class Config:
    """Application configuration."""
    
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
    
    # LangSmith settings
    LANGCHAIN_TRACING_V2: bool = os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    LANGCHAIN_API_KEY: str = os.getenv("LANGCHAIN_API_KEY", "")
    LANGCHAIN_PROJECT: str = os.getenv("LANGCHAIN_PROJECT", "music-store-support-bot")
    
    # Default user for demo
    DEFAULT_USER_ID: int = int(os.getenv("DEFAULT_USER_ID", "1"))
    
    # Checkpointer path
    CHECKPOINT_DB_PATH: str = os.getenv("CHECKPOINT_DB_PATH", "checkpoints.sqlite")


config = Config()

