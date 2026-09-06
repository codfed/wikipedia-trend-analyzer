"""One-off backfill: classify (topic, country) for trending_articles_v2 rows
saved before that classification existed (or after a taxonomy change), using
each row's own title+extract -- the same call main.py now runs live for
every newly-processed article (see main.py's _generate_summary_and_classify,
llm/prompts.py's SUMMARY_PROMPT, llm/topics.py).

Does NOT touch trending_reason/summary/anything else -- topic/country only.

Usage:
    TARGET_DATE=2026-09-04 python -m scripts.backfill_topics

    # Only fill rows that don't have a topic yet, skip already-classified ones
    TARGET_DATE=2026-09-04 SKIP_CLASSIFIED=1 python -m scripts.backfill_topics
"""
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from db.client import SupabaseClient
from llm.client import LLMClient
from llm.prompts import SUMMARY_MODEL, SUMMARY_TEMPERATURE, SUMMARY_MAX_TOKENS, SUMMARY_PROMPT
from llm.topics import clean_topic, clean_country

ARTICLE_TABLE = "trending_articles_v2"


def main() -> int:
    target_date_str = os.getenv("TARGET_DATE") or date.today().isoformat()
    target_date = date.fromisoformat(target_date_str)
    trending_date = (target_date - timedelta(days=1)).isoformat()
    print(f"TARGET_DATE={target_date_str} -> backfilling topics for trending_date={trending_date}")

    supabase_client = SupabaseClient()
    db = supabase_client.client
    llm_client = LLMClient()

    query = (
        db.table(ARTICLE_TABLE)
        .select("title,normalized_title,extract,topic")
        .eq("trending_date", trending_date)
    )
    if os.getenv("SKIP_CLASSIFIED"):
        query = query.is_("topic", "null")
    saved = query.execute().data

    if not saved:
        print(f"No articles to backfill for trending_date={trending_date}.")
        return 0
    print(f"Classifying {len(saved)} article(s)...")

    for row in saved:
        title = row["title"]
        prompt = SUMMARY_PROMPT.format(
            title=row["normalized_title"],
            extract=(row.get("extract") or "")[:1500],
        )
        data = llm_client.generate_json(
            prompt=prompt,
            model=SUMMARY_MODEL,
            temperature=SUMMARY_TEMPERATURE,
            max_tokens=SUMMARY_MAX_TOKENS,
        )
        topic = clean_topic(data.get("topic"))
        country = clean_country(data.get("country"))
        db.table(ARTICLE_TABLE).update({"topic": topic, "country": country}).eq(
            "title", title
        ).eq("trending_date", trending_date).execute()
        print(f"  {title}: topic={topic}, country={country}")

    print(f"\nBackfilled {len(saved)} article(s) for {trending_date}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
