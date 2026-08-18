"""TieredSearcher: runs search stages until a relevant result is found."""
import json
from dataclasses import dataclass
from typing import Optional

from pipeline.models import Article
from search.client import SerperClient


@dataclass
class SearchResult:
    stage: str          # "news" | "search" | "reddit" | "deep_search" | "unknown"
    query: str
    raw: str            # JSON string of the raw Serper response
    formatted: str      # human-readable summary for LLM prompts
    relevant: bool
    confidence: float


class TieredSearcher:
    """Runs news → web → reddit → deep search, stopping at first relevant result.

    Relevance gating is performed by an injected callable:
        is_relevant(article, formatted_results) -> (bool, float)
    This keeps the searcher decoupled from the LLM layer.
    """

    RELEVANCE_THRESHOLD = 0.65

    def __init__(
        self,
        serper_client: SerperClient,
        relevance_fn,          # callable(article, formatted) -> (bool, float)
        query_rewriter_fn,     # callable(article) -> str
    ):
        self.serper = serper_client
        self._is_relevant = relevance_fn
        self._rewrite_query = query_rewriter_fn

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def search(self, article: Article) -> SearchResult:
        query = article.normalized_title

        # Stage 1 — news search (past week)
        result = self._try_news(query, article)
        if result.relevant:
            return result

        # Stage 2 — web search (past week)
        result = self._try_web(query, article)
        if result.relevant:
            return result

        # Stage 3 — reddit search (past month)
        # Grassroots virality (TIL reposts, niche-subject threads) rarely uses
        # the article's exact title and often lags its source content by
        # weeks, so it needs a targeted query and a wider window than
        # stages 1–2.
        result = self._try_reddit(query, article)
        if result.relevant:
            return result

        # Stage 4 — deep search (rewritten query, past month)
        result = self._try_deep(article)
        if result.relevant:
            return result

        # All stages failed
        return SearchResult(
            stage="unknown",
            query=query,
            raw="",
            formatted="",
            relevant=False,
            confidence=0.0,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _try_news(self, query: str, article: Article) -> SearchResult:
        try:
            raw_data = self.serper.news(query, time_range="qdr:w")
        except Exception as e:
            print(f"  [tiered] news search failed: {e}")
            return self._empty_result("news", query)

        formatted = _format_news(raw_data)
        relevant, confidence = self._check_relevance(article, formatted, "news")
        return SearchResult(
            stage="news",
            query=query,
            raw=json.dumps(raw_data),
            formatted=formatted,
            relevant=relevant,
            confidence=confidence,
        )

    def _try_web(self, query: str, article: Article) -> SearchResult:
        try:
            raw_data = self.serper.search(query, time_range="qdr:w")
        except Exception as e:
            print(f"  [tiered] web search failed: {e}")
            return self._empty_result("search", query)

        formatted = _format_organic(raw_data)
        relevant, confidence = self._check_relevance(article, formatted, "search")
        return SearchResult(
            stage="search",
            query=query,
            raw=json.dumps(raw_data),
            formatted=formatted,
            relevant=relevant,
            confidence=confidence,
        )

    def _try_reddit(self, query: str, article: Article) -> SearchResult:
        reddit_query = f"site:reddit.com {query}"
        try:
            raw_data = self.serper.search(reddit_query, time_range="qdr:m")
        except Exception as e:
            print(f"  [tiered] reddit search failed: {e}")
            return self._empty_result("reddit", reddit_query)

        formatted = _format_organic(raw_data)
        relevant, confidence = self._check_relevance(article, formatted, "reddit")
        return SearchResult(
            stage="reddit",
            query=reddit_query,
            raw=json.dumps(raw_data),
            formatted=formatted,
            relevant=relevant,
            confidence=confidence,
        )

    def _try_deep(self, article: Article) -> SearchResult:
        try:
            rewritten = self._rewrite_query(article)
        except Exception as e:
            print(f"  [tiered] query rewrite failed: {e}")
            return self._empty_result("deep_search", article.normalized_title)

        print(f"  [tiered] deep search with rewritten query: {rewritten!r}")
        try:
            raw_data = self.serper.search(rewritten, time_range="qdr:m")
        except Exception as e:
            print(f"  [tiered] deep search request failed: {e}")
            return self._empty_result("deep_search", rewritten)

        formatted = _format_organic(raw_data)
        relevant, confidence = self._check_relevance(article, formatted, "deep_search")
        return SearchResult(
            stage="deep_search",
            query=rewritten,
            raw=json.dumps(raw_data),
            formatted=formatted,
            relevant=relevant,
            confidence=confidence,
        )

    def _check_relevance(
        self, article: Article, formatted: str, stage: str
    ) -> tuple[bool, float]:
        if not formatted:
            print(f"  [tiered] {stage}: no results returned")
            return False, 0.0
        try:
            relevant, confidence = self._is_relevant(article, formatted)
            print(
                f"  [tiered] {stage}: relevant={relevant}, confidence={confidence:.2f}"
            )
            return relevant, confidence
        except Exception as e:
            print(f"  [tiered] relevance check failed for {stage}: {e}")
            return False, 0.0

    @staticmethod
    def _empty_result(stage: str, query: str) -> SearchResult:
        return SearchResult(
            stage=stage, query=query, raw="", formatted="", relevant=False, confidence=0.0
        )


# ------------------------------------------------------------------
# Formatting helpers
# ------------------------------------------------------------------

def _format_news(data: dict) -> str:
    items = data.get("news", [])
    if not items:
        return ""
    lines = []
    for item in items[:10]:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        source = item.get("source", "")
        lines.append(f"{title} ({source}): {snippet}")
    return "\n".join(lines)


def _format_organic(data: dict) -> str:
    items = data.get("organic", [])
    if not items:
        return ""
    lines = []
    for item in items[:10]:
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        link = item.get("link", "")
        lines.append(f"{title} ({link}): {snippet}")
    return "\n".join(lines)
