"""Log the prompt version used for each pipeline run to Supabase."""
from datetime import datetime, timezone
from typing import Optional
from db.client import SupabaseClient

TABLE = "prompt_run_log"


class PromptTracker:
    """Records (date, prompt_version, article_count) after each run.

    Schema (prompt_run_log):
        id             uuid, primary key
        run_date       date
        prompt_version text
        article_count  int
        created_at     timestamptz
    """

    def __init__(self, supabase_client: Optional[SupabaseClient] = None):
        try:
            self._db = (supabase_client or SupabaseClient()).client
            self._available = True
        except ValueError:
            self._available = False

    def log_run(self, run_date: str, prompt_version: str, article_count: int) -> bool:
        if not self._available:
            return False
        try:
            self._db.table(TABLE).insert({
                "run_date": run_date,
                "prompt_version": prompt_version,
                "article_count": article_count,
            }).execute()
            return True
        except Exception as e:
            print(f"  [prompt_tracker] log failed: {e}")
            return False
