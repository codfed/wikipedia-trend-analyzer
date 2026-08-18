"""Example bank: store and retrieve high-scoring LLM outputs for few-shot injection."""
from typing import Optional
from db.client import SupabaseClient

TABLE = "example_bank"
MIN_SCORE = 4  # Only store examples with score >= this value


class ExampleBank:
    """Read/write interface for the example bank Supabase table.

    Schema (example_bank):
        id           uuid, primary key
        title        text
        trending_reason_source  text  ("news"|"search"|"reddit"|"deep_search")
        raw_input    text  (the formatted search results used)
        trending_reason  text
        score        int
        created_at   timestamptz
    """

    def __init__(self, supabase_client: Optional[SupabaseClient] = None):
        try:
            self._db = (supabase_client or SupabaseClient()).client
            self._available = True
        except ValueError:
            self._available = False

    def add_example(
        self,
        title: str,
        source: str,
        raw_input: str,
        trending_reason: str,
        score: int,
    ) -> bool:
        """Store a high-scoring example. Skips if score < MIN_SCORE or DB unavailable."""
        if not self._available or score < MIN_SCORE:
            return False
        try:
            self._db.table(TABLE).insert({
                "title": title,
                "trending_reason_source": source,
                "raw_input": raw_input[:4000],
                "trending_reason": trending_reason,
                "score": score,
            }).execute()
            return True
        except Exception as e:
            print(f"  [example_bank] insert failed: {e}")
            return False

    def get_examples(self, source: str, limit: int = 2) -> list[dict]:
        """Return top-scoring examples for a given source type."""
        if not self._available:
            return []
        try:
            result = (
                self._db.table(TABLE)
                .select("raw_input, trending_reason, score")
                .eq("trending_reason_source", source)
                .order("score", desc=True)
                .limit(limit)
                .execute()
            )
            return result.data or []
        except Exception as e:
            print(f"  [example_bank] fetch failed: {e}")
            return []

    def count(self) -> int:
        """Return total number of stored examples."""
        if not self._available:
            return 0
        try:
            result = self._db.table(TABLE).select("id", count="exact").execute()
            return result.count or 0
        except Exception:
            return 0
