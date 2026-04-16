"""Supabase connection wrapper."""
import os
from typing import Optional

from supabase import create_client, Client


class SupabaseClient:
    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
    ):
        self.url = url or os.getenv("SUPABASE_URL")
        self.key = key or os.getenv("SUPABASE_KEY")
        if not self.url or not self.key:
            raise ValueError(
                "Supabase URL and key required. "
                "Set SUPABASE_URL and SUPABASE_KEY environment variables."
            )
        self.client: Client = create_client(self.url, self.key)
