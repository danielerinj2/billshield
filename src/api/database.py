"""Supabase database client for FastAPI."""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

class Database:
    """Supabase database singleton."""
    
    _client: Client = None
    
    @classmethod
    def get_client(cls) -> Client:
        """Get or create Supabase client."""
        if cls._client is None:
            url = os.getenv("SUPABASE_URL")
            key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # Use service role for backend
            
            if not url or not key:
                raise ValueError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")
            
            cls._client = create_client(url, key)
        
        return cls._client

def get_db() -> Client:
    """Dependency injection for routes."""
    return Database.get_client()