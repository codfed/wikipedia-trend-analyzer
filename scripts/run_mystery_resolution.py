"""Standalone entry point: run piggyback + anniversary resolution for a date
whose per-article enrichment already ran and is saved in
trending_articles_v2 -- skips fetch/parse/tiered-search/eval entirely, and
only touches articles that are still is_mystery.

TARGET_DATE here means the same thing it means for main.py and
scripts/run_daily_summary.py: the featured-feed URL date, which always
reports on the PRIOR day's traffic. So TARGET_DATE=2026-09-09 resolves
mysteries for trending_date=2026-09-08, the date that was actually saved to
trending_articles_v2 when main.py last ran with that same TARGET_DATE.

Usage:
    TARGET_DATE=2026-09-09 python -m scripts.run_mystery_resolution

    # Report what would change without saving
    TARGET_DATE=2026-09-09 DRY_RUN=1 python -m scripts.run_mystery_resolution
"""
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from db.client import SupabaseClient
from db.saver import ArticleSaver
from llm.client import LLMClient
from llm.generator import ExplanationGenerator
from llm.relevance import is_relevant
from llm.prompts import PROMPT_VERSION
from memory.example_bank import ExampleBank
from pipeline.models import Article
from pipeline.piggyback import resolve_piggybacks, SOURCE_CROSS_REFERENCE, SOURCE_SEARCH_FALLBACK
from pipeline.anniversary import resolve_anniversaries, SOURCE_ANNIVERSARY
from search.client import SerperClient

from functools import partial

ARTICLE_TABLE = "trending_articles_v2"

# Every column ArticleSaver._to_dict() writes back on upsert -- selecting
# only the fields this script cares about would blank out view_count, rank,
# thumbnail, link, view_history, etc. on the resolved rows, since upsert
# writes the whole Article object, not just the fields we changed.
FIELDS = (
    "title,normalized_title,link,thumbnail,extract,view_count,rank,mystery_rank,"
    "view_history,is_newly_trending,view_delta_percentage,summary,topic,country,"
    "trending_reason,trending_reason_short,trending_reason_source,is_mystery,"
    "raw_search_results,search_query_used,carried_from_date"
)


def _row_to_article(row: dict, trending_date: str) -> Article:
    a = Article(
        date=trending_date,
        title=row["title"],
        normalized_title=row["normalized_title"] or row["title"],
    )
    a.link = row.get("link") or ""
    a.thumbnail = row.get("thumbnail")
    a.extract = row.get("extract") or ""
    a.view_count = row.get("view_count") or 0
    a.rank = row.get("rank") or 0
    a.mystery_rank = row.get("mystery_rank") or 0
    a.view_history = row.get("view_history") or []
    a.is_newly_trending = bool(row.get("is_newly_trending"))
    a.view_delta_percentage = row.get("view_delta_percentage") or 0
    a.summary = row.get("summary") or ""
    a.topic = row.get("topic") or "other"
    a.country = row.get("country")
    a.trending_reason = row.get("trending_reason") or ""
    a.trending_reason_short = row.get("trending_reason_short") or ""
    a.trending_reason_source = row.get("trending_reason_source") or "unknown"
    a.is_mystery = bool(row.get("is_mystery"))
    a.raw_search_results = row.get("raw_search_results") or ""
    a.search_query_used = row.get("search_query_used") or ""
    a.carried_from_date = row.get("carried_from_date")
    return a


def main() -> int:
    target_date_str = os.getenv("TARGET_DATE") or date.today().isoformat()
    target_date = date.fromisoformat(target_date_str)
    trending_date = (target_date - timedelta(days=1)).isoformat()
    print(f"TARGET_DATE={target_date_str} -> resolving mysteries for trending_date={trending_date}")

    supabase_client = SupabaseClient()
    db = supabase_client.client

    saved = (
        db.table(ARTICLE_TABLE)
        .select(FIELDS)
        .eq("trending_date", trending_date)
        .execute()
    ).data

    if not saved:
        print(
            f"No saved articles for trending_date={trending_date} -- "
            f"run 'TARGET_DATE={target_date_str} python main.py' first."
        )
        return 1

    processed = [_row_to_article(r, trending_date) for r in saved]
    mystery_count = sum(1 for a in processed if a.is_mystery)
    print(f"Found {len(processed)} saved article(s), {mystery_count} still mystery")
    for a in processed:
        if a.is_mystery:
            print(f"  - {a.title}")

    if mystery_count == 0:
        print("Nothing to resolve.")
        return 0

    llm_client = LLMClient()
    serper_client = SerperClient()
    relevance_fn = partial(is_relevant, llm_client=llm_client)
    generator = ExplanationGenerator(llm_client=llm_client, example_bank=ExampleBank())

    print(f"\n{'=' * 72}\nPiggyback cross-reference…\n{'=' * 72}")
    processed = resolve_piggybacks(processed, llm_client, serper_client, relevance_fn, generator)

    remaining = sum(1 for a in processed if a.is_mystery)
    print(f"\n{'=' * 72}\nAnniversary lead-up check ({remaining} still mystery)…\n{'=' * 72}")
    processed = resolve_anniversaries(processed, llm_client, serper_client)

    resolved = [
        a for a in processed
        if a.trending_reason_source in (SOURCE_CROSS_REFERENCE, SOURCE_SEARCH_FALLBACK, SOURCE_ANNIVERSARY)
    ]

    print(f"\n{'=' * 72}\nResolved {len(resolved)}/{mystery_count} mystery article(s):\n{'=' * 72}")
    for a in resolved:
        print(f"\n[{a.trending_reason_source}] {a.title}")
        print(f"  {a.trending_reason}")

    still_mystery = [a for a in processed if a.is_mystery]
    if still_mystery:
        print(f"\nStill unresolved: {[a.title for a in still_mystery]}")

    if os.getenv("DRY_RUN"):
        print("\nDRY_RUN set -- not saving.")
        return 0

    if resolved:
        saver = ArticleSaver(supabase_client)
        for a in resolved:
            ok = saver.save_article(a, PROMPT_VERSION)
            print(f"  {'saved' if ok else 'SAVE FAILED'}: {a.title}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
