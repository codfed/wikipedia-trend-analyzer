"""Persist daily_trend_rows -- one row per new/continuing trend or cluster."""
from db.client import SupabaseClient

TABLE = "daily_trend_rows"


class DailySummarySaver:
    """Schema (daily_trend_rows):
        id             uuid, primary key
        trending_date  date
        category       text  -- 'new' | 'new_cluster' | 'ongoing_trend' | 'ongoing_list' | 'ongoing_anomaly'
        titles         text[]
        headline       text
        summary        text
        image_url      text
        topic          text
        country        text  -- ISO 3166-1 alpha-2, nullable
        is_mystery     boolean default false
        streak_days    int
        trajectory     text
        prompt_version text
        created_at     timestamptz
    """

    def __init__(self, supabase_client: SupabaseClient):
        self._db = supabase_client.client

    def save_rows(self, trending_date: str, rows: list[dict], prompt_version: str) -> bool:
        """Replace all rows for trending_date with the given rows.

        Delete-then-insert rather than upsert -- clusters have no natural
        unique key (multiple titles per row), and a re-run for the same
        date (backfill retry, FORCE_REENRICH) should fully replace the
        prior rows rather than accumulate duplicates.
        """
        try:
            self._db.table(TABLE).delete().eq("trending_date", trending_date).execute()
            if not rows:
                return True
            payload = [
                {
                    "trending_date": trending_date,
                    "category": row["category"],
                    "titles": row["titles"],
                    "headline": row["headline"],
                    "summary": row["summary"],
                    "image_url": row.get("image_url"),
                    "topic": row.get("topic"),
                    "country": row.get("country"),
                    "is_mystery": row.get("is_mystery", False),
                    "streak_days": row.get("streak_days"),
                    "trajectory": row.get("trajectory"),
                    "prompt_version": prompt_version,
                }
                for row in rows
            ]
            self._db.table(TABLE).insert(payload).execute()
            return True
        except Exception as e:
            print(f"  [daily_summary_saver] save failed for {trending_date}: {e}")
            return False
