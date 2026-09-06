"""Standalone entry point: (re)build and save the daily trend digest for a
date whose per-article enrichment already ran and is saved in
trending_articles_v2 -- skips fetch/search/LLM-enrichment/eval entirely.

Useful for iterating on DailySummaryGenerator or the obituary row without
re-running (and re-billing) the full per-article pipeline.

TARGET_DATE here means the same thing it means for main.py and
scripts/run_pending.py: the featured-feed URL date, which always reports on
the PRIOR day's traffic. So TARGET_DATE=2026-09-03 rebuilds the digest for
trending_date=2026-09-02, the date that was actually saved to
trending_articles_v2 when main.py was run with that same TARGET_DATE. Passing
the trending_date directly here (off by one from every other script's
TARGET_DATE) is the single most likely way to get an empty or wrong digest.

Usage:
    TARGET_DATE=2026-09-03 python -m scripts.run_daily_summary

    # Print rows without writing to daily_trend_rows
    TARGET_DATE=2026-09-03 DRY_RUN=1 python -m scripts.run_daily_summary
"""
import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from db.client import SupabaseClient
from db.daily_summary_saver import DailySummarySaver
from llm.client import LLMClient
from llm.daily_summary import DailySummaryGenerator
from llm.prompts import PROMPT_VERSION
from pipeline.daily_stats import compute_daily_stats
from pipeline.deaths_scraper import DEATHS_ARTICLE_RE, build_obituary_row, scrape_deaths_for_date

ARTICLE_TABLE = "trending_articles_v2"


def main() -> int:
    target_date_str = os.getenv("TARGET_DATE") or date.today().isoformat()
    target_date = date.fromisoformat(target_date_str)
    trending_date = (target_date - timedelta(days=1)).isoformat()
    print(f"TARGET_DATE={target_date_str} -> building digest for trending_date={trending_date}")

    supabase_client = SupabaseClient()
    db = supabase_client.client

    saved = (
        db.table(ARTICLE_TABLE)
        .select(
            "normalized_title,title,thumbnail,trending_reason,trending_reason_short,"
            "topic,country,is_mystery"
        )
        .eq("trending_date", trending_date)
        .execute()
    ).data

    if not saved:
        print(
            f"No saved articles for trending_date={trending_date} -- "
            f"run 'TARGET_DATE={target_date_str} python main.py' first."
        )
        return 1
    print(f"Found {len(saved)} saved article(s)")

    titles = [r["normalized_title"] for r in saved]
    stats = compute_daily_stats(supabase_client, trending_date, titles)

    rows = DailySummaryGenerator(LLMClient()).generate(trending_date, saved, stats)

    # death_entries isn't persisted on trending_articles_v2 (see
    # pipeline/models.py), so the obituary row is rebuilt by re-scraping --
    # cheap and deterministic, no LLM call involved.
    year, month, day = (int(x) for x in trending_date.split("-"))
    for r in saved:
        title = r["normalized_title"] or r["title"]
        m = DEATHS_ARTICLE_RE.match(title or "")
        if not m:
            continue
        entries, _ = scrape_deaths_for_date(int(m.group(1)), month, day)
        if entries:
            rows.append(build_obituary_row(title, entries, stats))

    print(f"\nGenerated {len(rows)} row(s):")
    for row in rows:
        print(f"  [{row['category']}] {row['headline']!r} — titles={row['titles']}")

    if os.getenv("DRY_RUN"):
        print("\nDRY_RUN set — not saving.")
        return 0

    DailySummarySaver(supabase_client).save_rows(trending_date, rows, PROMPT_VERSION)
    print(f"\nSaved {len(rows)} row(s) to daily_trend_rows for {trending_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
