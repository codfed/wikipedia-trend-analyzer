"""Entry point: fetch → enrich → eval → save.

Usage:
    # Run for today
    python main.py

    # Run for a specific date
    TARGET_DATE=2026-04-12 python main.py

    # Single article (debug)
    TARGET_DATE=2026-04-12 TARGET_TITLE=Shmuel_Mikunis python main.py

    # Force re-enrichment for every article, ignoring carried-forward reasons
    TARGET_DATE=2026-04-12 FORCE_REENRICH=1 python main.py
"""

import os
import sys
import time
from datetime import date, datetime
from functools import partial

from dotenv import load_dotenv

load_dotenv()

from pipeline.fetcher import FeaturedFeedFetcher
from pipeline.parser import FeaturedArticlesParser
from pipeline.trending import calculate_trending_status
from pipeline.enricher import ArticleEnricher
from pipeline.deaths_scraper import DEATHS_ARTICLE_RE, build_obituary_row
from pipeline.models import Article

from search.client import SerperClient
from search.tiered import TieredSearcher
from search.query_rewriter import rewrite_query

from llm.client import LLMClient
from llm.prompts import (
    PROMPT_VERSION,
    SUMMARY_MODEL,
    SUMMARY_TEMPERATURE,
    SUMMARY_MAX_TOKENS,
    SUMMARY_PROMPT,
)
from llm.relevance import is_relevant
from llm.generator import ExplanationGenerator
from llm.topics import clean_topic, clean_country

from db.client import SupabaseClient
from db.saver import ArticleSaver

from memory.example_bank import ExampleBank
from memory.prompt_tracker import PromptTracker

from evals.runner import run_evals
from evals.judge import LLMJudge

from pipeline.daily_stats import compute_daily_stats
from llm.daily_summary import DailySummaryGenerator
from db.daily_summary_saver import DailySummarySaver

# If more than this fraction of articles error out of enrichment, treat the
# whole run as failed rather than silently continuing -- a high failure
# rate is almost always a systemic bug (bad prompt template, broken client)
# rather than one flaky article.
MAX_ARTICLE_FAILURE_RATE = float(os.getenv("MAX_ARTICLE_FAILURE_RATE", "0.2"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _title_match(needle: str, article: Article) -> bool:
    n = needle.lower().replace("_", " ")
    for field in (article.title, article.normalized_title):
        if field and n in field.lower().replace("_", " "):
            return True
    return False


def _generate_summary_and_classify(article: Article, llm_client: LLMClient) -> Article:
    """Always-run LLM call: produces article.summary plus content
    classification (topic/country). Bundled into one call since it already
    runs unconditionally for every article regardless of is_mystery status --
    classification rides along for free rather than needing its own call,
    and works for mystery articles since it only needs title+extract, not
    why the article is trending."""
    prompt = SUMMARY_PROMPT.format(
        title=article.normalized_title,
        extract=article.extract[:1500],
    )
    data = llm_client.generate_json(
        prompt=prompt,
        model=SUMMARY_MODEL,
        temperature=SUMMARY_TEMPERATURE,
        max_tokens=SUMMARY_MAX_TOKENS,
    )
    article.summary = data.get("summary", "")
    article.topic = clean_topic(data.get("topic"))
    article.country = clean_country(data.get("country"))
    return article


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    # --- Date / title filtering ---
    target_date: date | None = None
    target_date_str = os.getenv("TARGET_DATE")
    if target_date_str:
        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            print(f"Using TARGET_DATE: {target_date.isoformat()}")
        except ValueError:
            raise ValueError(
                f"Invalid TARGET_DATE: {target_date_str!r} — expected YYYY-MM-DD"
            )

    # --- Fetch & parse feed ---
    feed = FeaturedFeedFetcher().fetch(target_date=target_date)
    all_articles = FeaturedArticlesParser(feed).parse()

    force_reenrich = os.getenv("FORCE_REENRICH", "").lower() in ("1", "true", "yes")

    target_title = os.getenv("TARGET_TITLE")
    articles = all_articles
    if target_title:
        articles = [a for a in all_articles if _title_match(target_title, a)]
        print(f"Filtered to TARGET_TITLE={target_title!r}: {len(articles)} matched")
        if not articles:
            sample = ", ".join(repr(a.title) for a in all_articles[:15])
            print(f"Hint: no match. Titles that day: {sample}")

    if not articles:
        print("No articles to process.")
        return 1

    # --- Initialise clients ---
    llm_client = LLMClient()

    # Serper is optional — skip enrichment if not configured
    serper_client: SerperClient | None = None
    try:
        serper_client = SerperClient()
        print("Serper client initialised")
    except ValueError:
        print("Serper not configured — trending articles will be marked mystery")

    # Supabase is optional
    supabase_client: SupabaseClient | None = None
    article_saver: ArticleSaver | None = None
    example_bank = ExampleBank()
    prompt_tracker = PromptTracker()
    try:
        supabase_client = SupabaseClient()
        article_saver = ArticleSaver(supabase_client)
        print("Supabase client initialised")
    except ValueError:
        print("Supabase not configured — saves skipped")

    # Build the tiered searcher if Serper is available
    enricher: ArticleEnricher | None = None
    if serper_client:
        relevance_fn = partial(is_relevant, llm_client=llm_client)
        rewrite_fn = partial(rewrite_query, llm_client=llm_client)
        tiered_searcher = TieredSearcher(
            serper_client=serper_client,
            relevance_fn=relevance_fn,
            query_rewriter_fn=rewrite_fn,
        )
        generator = ExplanationGenerator(
            llm_client=llm_client,
            example_bank=example_bank if supabase_client else None,
        )
        enricher = ArticleEnricher(
            llm_client=llm_client,
            tiered_searcher=tiered_searcher,
            generator=generator,
        )

    # --- Process articles ---
    processed: list[Article] = []
    saves_ok = 0
    article_errors: list[str] = []

    for i, article in enumerate(articles, 1):
        print(f"\n{'=' * 72}")
        print(f"[{i}/{len(articles)}] {article.title}")
        print(f"{'=' * 72}")

        try:
            # 1. Trending status
            article = calculate_trending_status(article)
            print(
                f"  view_delta={article.view_delta_percentage}%, "
                f"is_newly_trending={article.is_newly_trending}"
            )

            # 2. Summary + content classification (always)
            t0 = time.perf_counter()
            article = _generate_summary_and_classify(article, llm_client)
            print(f"  summary ({time.perf_counter() - t0:.2f}s): {article.summary}")
            print(f"  topic={article.topic}, country={article.country}")

            # 3. Enrich — carry forward prior reason if available, else run pipeline
            # Rolling-list articles always re-scrape fresh — never carry forward
            always_fresh = bool(
                DEATHS_ARTICLE_RE.match(article.normalized_title or "")
                or DEATHS_ARTICLE_RE.match(article.title or "")
            )
            prior = article_saver.fetch_prior_reason(article.title, article.date) if (article_saver and not always_fresh) else None
            prior_days_old = (
                (datetime.strptime(article.date, "%Y-%m-%d").date()
                 - datetime.strptime(prior["trending_date"], "%Y-%m-%d").date()).days
                if prior else 0
            )
            if prior and force_reenrich:
                print(f"  [force_reenrich] ignoring carried-forward reason from {prior['trending_date']}")
            if prior and prior_days_old < 3 and not force_reenrich:
                article.trending_reason = prior["trending_reason"]
                article.trending_reason_short = prior["trending_reason_short"]
                article.trending_reason_source = "carried_forward"
                article.carried_from_date = prior["trending_date"]
                print(f"  [carried_forward] reused reason from {prior['trending_date']}")
            elif enricher:
                if prior:
                    print(f"  [re-enriching] prior reason is {prior_days_old} days old")
                article = enricher.enrich(article)
                print(
                    f"  source={article.trending_reason_source}, "
                    f"mystery={article.is_mystery}"
                )
                print(f"  reason: {article.trending_reason[:120]}")
                print(f"  short:  {article.trending_reason_short}")
            else:
                print("  [skipping enrichment — Serper not configured]")

            # 4. Save
            if article_saver:
                ok = article_saver.save_article(article, PROMPT_VERSION)
                if ok:
                    saves_ok += 1
                    print(f"  Saved to Supabase")
                else:
                    print(f"  Save failed")
            else:
                print("  [no Supabase — save skipped]")

            processed.append(article)

        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback

            traceback.print_exc()
            print("  Continuing to next article…")
            article_errors.append(f"{article.title}: {e}")

    # --- Run evals on just-processed articles ---
    enriched = [a for a in processed if a.trending_reason]
    if enriched and not os.getenv("SKIP_EVALS"):
        print(f"\n{'=' * 72}")
        print(f"Running evals on {len(enriched)} enriched article(s)…")
        print(f"{'=' * 72}")
        run_evals(
            enriched, llm_client, db_saver=article_saver, prompt_version=PROMPT_VERSION
        )

        # Store high-scoring outputs in example bank
        if supabase_client:
            _maybe_store_examples(enriched, llm_client, example_bank)

    # --- Log run ---
    if supabase_client and processed:
        date_str = processed[0].date
        prompt_tracker.log_run(date_str, PROMPT_VERSION, len(processed))

    # --- Daily trend summary (new/continuing rows, once per date) ---
    daily_summary_failed = False
    if supabase_client and processed and not os.getenv("SKIP_DAILY_SUMMARY"):
        date_str = processed[0].date
        print(f"\n{'=' * 72}")
        print(f"Building daily trend summary for {date_str}…")
        print(f"{'=' * 72}")
        try:
            titles = [a.normalized_title for a in processed]
            stats = compute_daily_stats(supabase_client, date_str, titles)
            rows = DailySummaryGenerator(llm_client).generate(
                date_str, [a.to_dict() for a in processed], stats
            )

            # Obituary row: deterministic, not LLM-generated -- it's just
            # today's slice of the "Deaths in YYYY" rolling list, already
            # scraped verbatim by pipeline/deaths_scraper.py. No synthesis
            # needed, so it's built here rather than routed through
            # DailySummaryGenerator's new-article clustering prompt.
            for article in processed:
                if not article.death_entries:
                    continue
                rows.append(build_obituary_row(article.normalized_title, article.death_entries, stats))

            DailySummarySaver(supabase_client).save_rows(date_str, rows, PROMPT_VERSION)
            print(f"  Saved {len(rows)} daily trend row(s)")
        except Exception as e:
            print(f"  [daily_summary] failed: {e}")
            import traceback

            traceback.print_exc()
            daily_summary_failed = True

    print(f"\n{'=' * 72}")
    print(f"Done. Processed={len(processed)}, Saves={saves_ok}/{len(articles)}")
    print(f"Prompt version: {PROMPT_VERSION}")
    print(f"{'=' * 72}")

    # --- Decide run status ---
    # Per-article exceptions are swallowed above so one flaky article
    # doesn't sink the whole run, but a high failure rate usually means a
    # systemic bug (e.g. a bad prompt template) silently eating every
    # article -- that must fail the job loudly, not print-and-continue.
    run_failed = False

    if article_saver and saves_ok == 0 and articles:
        print("ERROR: all Supabase saves failed.")
        run_failed = True

    if article_errors:
        failure_rate = len(article_errors) / len(articles)
        print(f"\n{len(article_errors)}/{len(articles)} article(s) failed:")
        for line in article_errors:
            print(f"  - {line}")
        if failure_rate > MAX_ARTICLE_FAILURE_RATE:
            print(
                f"ERROR: article failure rate {failure_rate:.0%} exceeds "
                f"{MAX_ARTICLE_FAILURE_RATE:.0%} threshold."
            )
            run_failed = True

    if daily_summary_failed:
        print("ERROR: daily trend summary failed.")
        run_failed = True

    return 1 if run_failed else 0


def _maybe_store_examples(
    articles: list[Article],
    llm_client: LLMClient,
    bank: ExampleBank,
) -> None:
    """Score enriched articles and store high-scorers in the example bank."""
    judge = LLMJudge(llm_client)
    for article in articles:
        if article.is_mystery or not article.raw_search_results:
            continue
        try:
            result = judge.score_trending_reason(article, article.raw_search_results)
            if result.score >= 4:
                bank.add_example(
                    title=article.title,
                    source=article.trending_reason_source,
                    raw_input=article.raw_search_results[:3000],
                    trending_reason=article.trending_reason,
                    score=result.score,
                )
                print(
                    f"  [example_bank] stored example for {article.title} "
                    f"(score={result.score})"
                )
        except Exception as e:
            print(f"  [example_bank] scoring failed for {article.title}: {e}")


if __name__ == "__main__":
    sys.exit(main())
