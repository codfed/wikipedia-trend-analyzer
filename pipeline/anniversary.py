"""Resolve is_mystery articles that are trending in the lead-up to a
calendar anniversary of a historical event they're closely associated with
(e.g. "Falling Man" spiking in the days before September 11) -- tiered
search finds nothing because there's no current news, just proximity to a
date. Unlike piggyback.py, this doesn't need another article to already be
trending the same day; the reference point is the calendar, not the day's
other trends.

Runs after piggyback resolution has already had a shot at the mystery
queue (see main.py). Three stages, each gating the next:

1. LLM world-knowledge query (ANNIVERSARY_DETECT_PROMPT): is this article's
   subject associated with a specific historical event tied to a calendar
   date? This is the one place in the pipeline that leans on the model's
   own knowledge rather than search results or a hand-curated list, since
   the set of possible anniversary-adjacent articles (any 9/11-, Pearl
   Harbor-, D-Day-adjacent page) is unbounded -- so every claim from this
   step is treated as unverified until stage 3 confirms it.
2. Deterministic date-proximity check (anniversary_dates.py): is the
   claimed date within the lead-up window? No LLM involved, just calendar
   math, same spirit as holiday_dates.py.
3. Grounding search + verification: a real Serper search for the article
   title alongside the claimed event, gated by an LLM check
   (ANNIVERSARY_VERIFY_PROMPT) that the results actually substantiate the
   connection rather than just topical overlap. Only a confirmed
   connection resolves the mystery; unconfirmed candidates are left alone.
"""
import json
from datetime import datetime

from pipeline.models import Article
from pipeline.anniversary_dates import describe_anniversary_proximity
from search.client import SerperClient
from search.tiered import date_window, format_organic
from llm.client import LLMClient
from llm.prompts import (
    ANNIVERSARY_DETECT_MODEL,
    ANNIVERSARY_DETECT_TEMPERATURE,
    ANNIVERSARY_DETECT_MAX_TOKENS,
    ANNIVERSARY_DETECT_PROMPT,
    ANNIVERSARY_VERIFY_MODEL,
    ANNIVERSARY_VERIFY_TEMPERATURE,
    ANNIVERSARY_VERIFY_MAX_TOKENS,
    ANNIVERSARY_VERIFY_PROMPT,
    ANNIVERSARY_EXPLANATION_MODEL,
    ANNIVERSARY_EXPLANATION_TEMPERATURE,
    ANNIVERSARY_EXPLANATION_MAX_TOKENS,
    ANNIVERSARY_EXPLANATION_PROMPT,
    SHORT_MODEL,
    SHORT_TEMPERATURE,
    SHORT_MAX_TOKENS,
    SHORT_PROMPT,
)

# Soft pre-filter before bothering with a search call -- stage 3's
# verification is the real gate, so this only needs to screen out the
# model declining to guess at all (confidence near 0).
DETECT_CONFIDENCE_THRESHOLD = 0.5

# Matches RELEVANCE_THRESHOLD / piggyback's bar for trusting a positive gate.
VERIFY_CONFIDENCE_THRESHOLD = 0.65

# Verifying a historical fact, not hunting for recent news, so the grounding
# search is given a wide time window rather than the tight ones tiered
# search uses -- the confirming source could be decades old or written
# yesterday.
GROUNDING_SEARCH_DAYS_BACK = 36500  # ~100 years

SOURCE_ANNIVERSARY = "anniversary"


def resolve_anniversaries(
    processed: list[Article],
    llm_client: LLMClient,
    serper_client: SerperClient | None,
) -> list[Article]:
    """Mutates and returns `processed`, resolving as many is_mystery
    articles as are plausibly trending ahead of a calendar anniversary."""
    if not serper_client:
        return processed

    for article in processed:
        if not article.is_mystery:
            continue
        try:
            _resolve_one(article, llm_client, serper_client)
        except Exception as e:
            print(f"  [anniversary] failed for {article.title}: {e}")

    return processed


def _resolve_one(article: Article, llm_client: LLMClient, serper_client: SerperClient) -> None:
    detect_prompt = ANNIVERSARY_DETECT_PROMPT.format(
        title=article.normalized_title,
        summary=article.summary or article.extract[:200],
    )
    detect = llm_client.generate_json(
        prompt=detect_prompt,
        model=ANNIVERSARY_DETECT_MODEL,
        temperature=ANNIVERSARY_DETECT_TEMPERATURE,
        max_tokens=ANNIVERSARY_DETECT_MAX_TOKENS,
    )
    event = (detect.get("event") or "").strip() or None
    month_day = detect.get("date_mm_dd") or None
    confidence = float(detect.get("confidence", 0.0))

    if not event or not month_day or confidence < DETECT_CONFIDENCE_THRESHOLD:
        return

    target_date = datetime.strptime(article.date, "%Y-%m-%d").date()
    proximity = describe_anniversary_proximity(month_day, target_date)
    if proximity is None:
        print(
            f"  [anniversary] {article.title}: candidate {event!r} ({month_day}) "
            f"not in lead-up window"
        )
        return

    print(
        f"  [anniversary] {article.title}: candidate={event!r}, "
        f"{proximity['days_until']}d out, verifying via search…"
    )

    query = f"{article.normalized_title} {event}"
    try:
        raw_data = serper_client.search(
            query, time_range=date_window(article, GROUNDING_SEARCH_DAYS_BACK)
        )
    except Exception as e:
        print(f"  [anniversary] grounding search failed: {e}")
        return

    formatted = format_organic(raw_data)
    if not formatted:
        print("  [anniversary] grounding search: no results")
        return

    verify_prompt = ANNIVERSARY_VERIFY_PROMPT.format(
        title=article.normalized_title, event=event, results=formatted[:3000],
    )
    verify = llm_client.generate_json(
        prompt=verify_prompt,
        model=ANNIVERSARY_VERIFY_MODEL,
        temperature=ANNIVERSARY_VERIFY_TEMPERATURE,
        max_tokens=ANNIVERSARY_VERIFY_MAX_TOKENS,
    )
    confirmed = bool(verify.get("confirmed"))
    verify_confidence = float(verify.get("confidence", 0.0))
    print(f"  [anniversary] verify: confirmed={confirmed}, confidence={verify_confidence:.2f}")

    if not confirmed or verify_confidence < VERIFY_CONFIDENCE_THRESHOLD:
        return

    explanation_prompt = ANNIVERSARY_EXPLANATION_PROMPT.format(
        title=article.normalized_title,
        summary=article.summary or article.extract[:200],
        event=event,
        date_phrase=proximity["date_phrase"],
        weekday_phrase=proximity["weekday_phrase"],
        days_until=proximity["days_until"],
        results=formatted[:3000],
    )
    reason = llm_client.generate(
        prompt=explanation_prompt,
        model=ANNIVERSARY_EXPLANATION_MODEL,
        temperature=ANNIVERSARY_EXPLANATION_TEMPERATURE,
        max_tokens=ANNIVERSARY_EXPLANATION_MAX_TOKENS,
    )

    short_prompt = SHORT_PROMPT.format(
        title=article.normalized_title,
        summary=article.summary or article.extract[:200],
        trending_reason=reason,
    )
    reason_short = llm_client.generate(
        prompt=short_prompt, model=SHORT_MODEL, temperature=SHORT_TEMPERATURE, max_tokens=SHORT_MAX_TOKENS,
    )

    article.trending_reason = reason
    article.trending_reason_short = reason_short
    article.trending_reason_source = SOURCE_ANNIVERSARY
    article.raw_search_results = json.dumps(raw_data)
    article.search_query_used = query
    article.is_mystery = False
    print(f"  [anniversary] resolved: {article.title} -> {event}")
