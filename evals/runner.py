"""Eval runner: scores articles, prints report, optionally saves to Supabase.

Usage:
    python evals/runner.py --date 2026-04-12
    python evals/runner.py --date 2026-04-12 --title Shmuel_Mikunis
    python evals/runner.py --flagged      # articles with flag_for_test=True

Exit code 0 if all evaluated fields pass, non-zero otherwise.
"""
import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pipeline.models import Article
from llm.client import LLMClient
from llm.prompts import PROMPT_VERSION
from evals.judge import LLMJudge, EvalResult
from evals.metrics import run_deterministic_checks, MetricResult
from evals.fixtures import fetch_flagged_articles

_SKIPPED = object()


def run_evals(
    articles: list[Article],
    llm_client: LLMClient,
    db_saver=None,
    prompt_version: str = PROMPT_VERSION,
) -> int:
    """Score articles and return exit code (0 = all pass)."""
    judge = LLMJudge(llm_client)
    rows = []

    for article in articles:
        label = f"{article.title} ({article.date})"
        print(f"\n{'─' * 60}")
        print(f"Article: {label}")
        print(f"  source={article.trending_reason_source}, mystery={article.is_mystery}")
        print(f"{'─' * 60}")

        # Deterministic checks first
        det_results = run_deterministic_checks(article)
        for r in det_results:
            mark = "✓" if r.passed else "✗"
            print(f"  [{mark}] {r.check}: {r.detail}")
            rows.append({"label": label, "field": r.check, "result": r, "type": "metric"})

        # LLM judging
        print("  Judging with LLM…", end=" ", flush=True)
        reason_result = (
            judge.score_trending_reason(article, article.raw_search_results)
            if article.trending_reason
            else _SKIPPED
        )
        short_result = (
            judge.score_trending_reason_short(article)
            if article.trending_reason_short
            else _SKIPPED
        )
        print("done")

        rows.append({"label": label, "field": "trending_reason", "result": reason_result, "type": "llm"})
        rows.append({"label": label, "field": "trending_reason_short", "result": short_result, "type": "llm"})

        # Optionally persist eval results
        if db_saver:
            _save_eval_rows(db_saver, article, [reason_result, short_result], prompt_version)

    # Summary table
    col_label = 38
    col_field = 30
    total_width = col_label + col_field + 12 + 60
    print(f"\n{'=' * total_width}")
    print(f"{'Article':<{col_label}} {'Field':<{col_field}} {'Score':>5} {'Pass':>5}  Reasoning")
    print(f"{'-' * total_width}")

    passed_count = 0
    judged_count = 0

    for row in rows:
        r = row["result"]
        field = row["field"]
        label = row["label"]

        if r is _SKIPPED:
            print(f"{label[:col_label]:<{col_label}} {field:<{col_field}} {'N/A':>5} {'–':>5}  (skipped)")
            continue

        if row["type"] == "metric":
            mark = "✓" if r.passed else "✗"
            score_str = "–"
            detail = r.detail[:55]
        else:
            judged_count += 1
            if r.passed:
                passed_count += 1
            mark = "✓" if r.passed else "✗"
            score_str = str(r.score)
            detail = (r.reasoning[:55] + "…") if len(r.reasoning) > 55 else r.reasoning

        print(
            f"{label[:col_label]:<{col_label}} {field:<{col_field}} "
            f"{score_str:>5} {mark:>5}  {detail}"
        )

    print(f"{'=' * total_width}")
    print(f"\nLLM judge pass rate: {passed_count}/{judged_count}")

    return 0 if passed_count == judged_count else 1


def _save_eval_rows(db_saver, article, results, prompt_version):
    """Persist eval results to Supabase eval_results table."""
    for r in results:
        if r is _SKIPPED:
            continue
        try:
            db_saver.save_eval_result(
                title=article.title,
                date=article.date,
                field=r.field,
                score=r.score,
                reasoning=r.reasoning,
                passed=r.passed,
                prompt_version=prompt_version,
            )
        except Exception as e:
            print(f"  [runner] failed to save eval result: {e}")


def _fetch_articles_for_date(date_str: str, title_filter: str | None) -> list[Article]:
    """Load articles from Supabase by trending_date."""
    from db.client import SupabaseClient
    from evals.fixtures import _row_to_article

    db = SupabaseClient()
    query = db.client.table("trending_articles_v2").select("*").eq("trending_date", date_str)
    result = query.execute()
    articles = [_row_to_article(row) for row in result.data]
    if title_filter:
        articles = [a for a in articles if title_filter.lower() in a.title.lower()]
    return articles


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run evals on v2 pipeline outputs.")
    parser.add_argument("--date", default=None, help="Trending date (YYYY-MM-DD)")
    parser.add_argument("--title", default=None, help="Filter by title substring")
    parser.add_argument("--flagged", action="store_true", help="Use flag_for_test=True articles")
    args = parser.parse_args()

    llm_client = LLMClient()

    if args.flagged:
        articles = fetch_flagged_articles()
        if args.title:
            articles = [a for a in articles if args.title.lower() in a.title.lower()]
    elif args.date:
        articles = _fetch_articles_for_date(args.date, args.title)
    else:
        print("Provide --date YYYY-MM-DD or --flagged")
        sys.exit(1)

    if not articles:
        print("No articles found.")
        sys.exit(0)

    sys.exit(run_evals(articles, llm_client))
