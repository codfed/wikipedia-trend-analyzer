"""Persist Article objects and eval results to Supabase."""
from typing import Optional

from pipeline.models import Article
from db.client import SupabaseClient

ARTICLE_TABLE = "trending_articles_v2"
EVAL_TABLE = "eval_results"


class ArticleSaver:
    def __init__(self, supabase_client: SupabaseClient):
        self._db = supabase_client.client

    def save_article(self, article: Article, prompt_version: str) -> bool:
        """Upsert article to Supabase. Returns True on success."""
        data = self._to_dict(article, prompt_version)
        try:
            self._db.table(ARTICLE_TABLE).upsert(
                data, on_conflict="title,trending_date"
            ).execute()
            return True
        except Exception as e:
            print(f"  [saver] insert failed for {article.title}: {e}")
            return False

    def save_eval_result(
        self,
        title: str,
        date: str,
        field: str,
        score: int,
        reasoning: str,
        passed: bool,
        prompt_version: str,
    ) -> bool:
        """Append an eval result row."""
        try:
            self._db.table(EVAL_TABLE).insert({
                "title": title,
                "trending_date": date,
                "field": field,
                "score": score,
                "reasoning": reasoning,
                "passed": passed,
                "prompt_version": prompt_version,
            }).execute()
            return True
        except Exception as e:
            print(f"  [saver] eval insert failed: {e}")
            return False

    @staticmethod
    def _to_dict(article: Article, prompt_version: str) -> dict:
        return {
            "trending_date": article.date,
            "title": article.title,
            "normalized_title": article.normalized_title,
            "link": article.link,
            "thumbnail": article.thumbnail,
            "extract": article.extract,
            "view_count": article.view_count,
            "rank": article.rank,
            "mystery_rank": article.mystery_rank,
            "view_history": article.view_history or None,
            "is_newly_trending": article.is_newly_trending,
            "view_delta_percentage": article.view_delta_percentage,
            "summary": article.summary,
            "trending_reason": article.trending_reason,
            "trending_reason_short": article.trending_reason_short,
            "trending_reason_source": article.trending_reason_source,
            "is_mystery": article.is_mystery,
            "raw_search_results": article.raw_search_results or None,
            "search_query_used": article.search_query_used,
            "prompt_version": prompt_version,
        }
