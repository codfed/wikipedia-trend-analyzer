"""Orchestrate the tiered search + LLM enrichment for a single article."""

import calendar
import time
from pipeline.deaths_scraper import scrape_deaths_for_date, DEATHS_ARTICLE_RE
from pipeline.models import Article
from search.tiered import TieredSearcher, SearchResult
from llm.generator import ExplanationGenerator
from llm.client import LLMClient
from llm.prompts import PROMPT_VERSION


class ArticleEnricher:
    """Runs the full enrichment pipeline for a single article:
    1. Tiered search (news → web → deep)
    2. Generate trending_reason + trending_reason_short from best result
    3. Populate article fields
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tiered_searcher: TieredSearcher,
        generator: ExplanationGenerator,
    ):
        self.llm_client = llm_client
        self.tiered_searcher = tiered_searcher
        self.generator = generator

    def enrich(self, article: Article) -> Article:
        """Run tiered search and generate explanation. Returns mutated article."""
        m = DEATHS_ARTICLE_RE.match(article.title)
        if m:
            return self._enrich_deaths_article(article, int(m.group(1)))

        print(f"  [enricher] Running tiered search for: {article.title}")
        t0 = time.perf_counter()
        result: SearchResult = self.tiered_searcher.search(article)
        elapsed = time.perf_counter() - t0
        print(
            f"  [enricher] Search complete in {elapsed:.2f}s — "
            f"stage={result.stage}, relevant={result.relevant}, "
            f"confidence={result.confidence:.2f}"
        )

        article.raw_search_results = result.raw
        article.search_query_used = result.query
        article.trending_reason_source = result.stage

        if not result.relevant:
            article.is_mystery = True
            article.trending_reason = "Unclear why this article is trending."
            article.trending_reason_short = "Unclear why this article is trending."
            print(f"  [enricher] No relevant results found — marked as mystery")
            return article

        print(f"  [enricher] Generating explanation from {result.stage} results…")
        t0 = time.perf_counter()
        reason, reason_short = self.generator.generate(article, result)
        elapsed = time.perf_counter() - t0
        print(f"  [enricher] Explanation generated in {elapsed:.2f}s")

        article.trending_reason = reason
        article.trending_reason_short = reason_short
        return article

    def _enrich_deaths_article(self, article: Article, year: int) -> Article:
        """Special-case handler for 'Deaths in YYYY' rolling-list articles."""
        _, month, day = (int(x) for x in article.date.split("-"))
        entries, raw_section = scrape_deaths_for_date(year, month, day)

        month_name = calendar.month_name[month]
        if entries:
            deaths_block = "\n".join(f"• {e}" for e in entries)
            reason = (
                f"List updated daily with deaths of notable figures.\n\n"
                f"Notable deaths on {month_name} {day}:\n{deaths_block}"
            )
        else:
            reason = "List updated daily with deaths of notable figures."

        api_url = f"https://en.wikipedia.org/w/api.php?action=parse&page=Deaths_in_{year}&prop=wikitext&format=json"
        article.trending_reason = reason
        article.trending_reason_short = reason
        article.trending_reason_source = "rolling_list"
        article.raw_search_results = raw_section
        article.search_query_used = api_url
        article.is_mystery = False
        article.death_entries = entries
        print(
            f"  [enricher] Deaths article — scraped {len(entries)} entries "
            f"for {month_name} {day}"
        )
        return article
