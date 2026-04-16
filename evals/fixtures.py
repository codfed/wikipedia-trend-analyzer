"""Fetch eval fixtures from Supabase (articles flagged with flag_for_test=True)."""
from db.client import SupabaseClient
from pipeline.models import Article

TABLE = "trending_articles_v2"


def fetch_flagged_articles() -> list[Article]:
    """Fetch articles where flag_for_test=True from Supabase."""
    db = SupabaseClient()
    result = (
        db.client.table(TABLE).select("*").eq("flag_for_test", True).execute()
    )
    return [_row_to_article(row) for row in result.data]


def _row_to_article(row: dict) -> Article:
    return Article(
        date=row.get("trending_date", ""),
        title=row.get("title", ""),
        normalized_title=row.get("normalized_title", ""),
        extract=row.get("extract", ""),
        summary=row.get("summary", ""),
        link=row.get("link", ""),
        thumbnail=row.get("thumbnail"),
        view_count=row.get("view_count", 0),
        rank=row.get("rank", 0),
        mystery_rank=row.get("mystery_rank", 0),
        view_history=row.get("view_history") or [],
        is_newly_trending=row.get("is_newly_trending", False),
        view_delta_percentage=row.get("view_delta_percentage", 0),
        trending_reason=row.get("trending_reason", ""),
        trending_reason_short=row.get("trending_reason_short", ""),
        trending_reason_source=row.get("trending_reason_source", "unknown"),
        is_mystery=row.get("is_mystery", False),
        raw_search_results=row.get("raw_search_results") or "",
        search_query_used=row.get("search_query_used", ""),
    )
