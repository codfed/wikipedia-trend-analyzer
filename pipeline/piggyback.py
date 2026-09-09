"""Cross-reference is_mystery articles against the same date's other trending
articles to catch piggybacking: a spike with no findable news story of its
own because it's just riding another story that trended the same day (e.g.
"United States" spiking alongside "Labor Day"). Runs once per date, after
the whole day's per-article loop has produced real trending_reasons for
everything else -- mirrors DailySummaryGenerator in shape (one pass needs
the whole day's list to have anything to cross-reference against), but
resolves individual mystery articles rather than building digest rows.

Two-stage per mystery article, cheapest first:
1. LLM cross-reference against the day's already-known reasons -- no new
   search call. If the model is confident, done.
2. Serper fallback: only when the model named a real candidate but wasn't
   confident enough on its own -- one targeted search seeded with that
   candidate's title, then the normal relevance gate + explanation
   generator take over exactly as they do for tiered search.
Articles that clear neither stage are left untouched, still mystery.
"""
import json

from pipeline.models import Article
from search.client import SerperClient
from search.tiered import SearchResult, date_window, format_organic
from llm.client import LLMClient
from llm.generator import ExplanationGenerator
from llm.prompts import (
    PIGGYBACK_MODEL,
    PIGGYBACK_TEMPERATURE,
    PIGGYBACK_MAX_TOKENS,
    PIGGYBACK_PROMPT,
)

RELATED_CONFIDENCE_THRESHOLD = 0.65

SOURCE_CROSS_REFERENCE = "piggyback"
SOURCE_SEARCH_FALLBACK = "piggyback_search"

# Sources that carry a real, already-known reason worth cross-referencing
# against. Excludes other still-unresolved mysteries -- there's nothing
# there to explain anything with.
_EXPLAINED_SOURCES = {
    "news", "search", "reddit", "deep_search",
    "holiday", "rolling_list", "carried_forward",
}


def resolve_piggybacks(
    processed: list[Article],
    llm_client: LLMClient,
    serper_client: SerperClient | None,
    relevance_fn,
    generator: ExplanationGenerator,
) -> list[Article]:
    """Mutates and returns `processed`, resolving as many is_mystery
    articles as plausibly piggyback on one of that date's other trends."""
    mysteries = [a for a in processed if a.is_mystery]
    if not mysteries:
        return processed

    explained = [a for a in processed if a.trending_reason_source in _EXPLAINED_SOURCES]
    if not explained:
        return processed

    day_context = "\n".join(
        f"- {a.normalized_title}: {a.trending_reason_short or a.trending_reason}"
        for a in explained
    )
    valid_titles = {a.normalized_title for a in explained}

    for article in mysteries:
        try:
            _resolve_one(article, day_context, valid_titles, llm_client, serper_client, relevance_fn, generator)
        except Exception as e:
            print(f"  [piggyback] failed for {article.title}: {e}")

    return processed


def _resolve_one(
    article: Article,
    day_context: str,
    valid_titles: set[str],
    llm_client: LLMClient,
    serper_client: SerperClient | None,
    relevance_fn,
    generator: ExplanationGenerator,
) -> None:
    prompt = PIGGYBACK_PROMPT.format(
        title=article.normalized_title,
        summary=article.summary or article.extract[:200],
        day_context=day_context,
    )
    data = llm_client.generate_json(
        prompt=prompt,
        model=PIGGYBACK_MODEL,
        temperature=PIGGYBACK_TEMPERATURE,
        max_tokens=PIGGYBACK_MAX_TOKENS,
    )
    candidate_title = data.get("candidate_title") or None
    confidence = float(data.get("confidence", 0.0))
    explanation = (data.get("explanation") or "").strip()

    if candidate_title not in valid_titles:
        candidate_title = None

    print(
        f"  [piggyback] {article.title}: candidate={candidate_title!r}, "
        f"confidence={confidence:.2f}"
    )

    if candidate_title is None:
        return

    if confidence >= RELATED_CONFIDENCE_THRESHOLD:
        _apply_cross_reference(article, candidate_title, explanation)
        return

    if serper_client:
        _try_search_fallback(article, candidate_title, serper_client, relevance_fn, generator)


def _apply_cross_reference(article: Article, candidate_title: str, explanation: str) -> None:
    reason = explanation or (
        f"{article.normalized_title} is trending alongside {candidate_title}, which is "
        f"trending the same day, likely driven by the same wave of reader interest."
    )
    article.trending_reason = reason
    article.trending_reason_short = reason
    article.trending_reason_source = SOURCE_CROSS_REFERENCE
    article.is_mystery = False
    article.search_query_used = f"[piggyback:{candidate_title}]"
    print(f"  [piggyback] resolved via cross-reference against {candidate_title!r}")


def _try_search_fallback(
    article: Article,
    candidate_title: str,
    serper_client: SerperClient,
    relevance_fn,
    generator: ExplanationGenerator,
) -> None:
    query = f"{article.normalized_title} {candidate_title}"
    try:
        raw_data = serper_client.search(query, time_range=date_window(article, 7))
    except Exception as e:
        print(f"  [piggyback] fallback search failed: {e}")
        return

    formatted = format_organic(raw_data)
    if not formatted:
        print("  [piggyback] fallback search: no results")
        return

    relevant, confidence = relevance_fn(article, formatted)
    print(f"  [piggyback] fallback search: relevant={relevant}, confidence={confidence:.2f}")
    if not relevant:
        return

    result = SearchResult(
        stage=SOURCE_SEARCH_FALLBACK,
        query=query,
        raw=json.dumps(raw_data),
        formatted=formatted,
        relevant=True,
        confidence=confidence,
    )
    reason, reason_short = generator.generate(article, result)

    article.trending_reason = reason
    article.trending_reason_short = reason_short
    article.trending_reason_source = SOURCE_SEARCH_FALLBACK
    article.raw_search_results = result.raw
    article.search_query_used = query
    article.is_mystery = False
    print(f"  [piggyback] resolved via fallback search seeded with {candidate_title!r}")
