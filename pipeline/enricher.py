"""Orchestrate the tiered search + LLM enrichment for a single article."""

import calendar
import time
from datetime import datetime
from pipeline.deaths_scraper import scrape_deaths_for_date, DEATHS_ARTICLE_RE
from pipeline.holiday_dates import describe_holiday_date
from pipeline.models import Article
from search.tiered import TieredSearcher, SearchResult
from llm.generator import ExplanationGenerator
from llm.client import LLMClient
from llm.prompts import (
    PROMPT_VERSION,
    HOLIDAY_EXPLANATION_MODEL,
    HOLIDAY_EXPLANATION_TEMPERATURE,
    HOLIDAY_EXPLANATION_MAX_TOKENS,
    HOLIDAY_EXPLANATION_PROMPT,
    SHORT_MODEL,
    SHORT_TEMPERATURE,
    SHORT_MAX_TOKENS,
    SHORT_PROMPT,
)

# Recurring calendar holidays reliably trend every year on their date with no
# actual news story behind them -- there's nothing for tiered search to find,
# so it inconsistently marks them mystery depending on whatever incidental
# press coverage happens to exist that year (observed: the same holiday
# flips mystery true/false year to year). Hand-maintained like
# BOT_TRAFFIC_TITLES (pipeline/daily_stats.py) since there's no reliable
# structural signal to detect "this title is a holiday" -- expand as new
# ones are spotted trending as mysteries.
HOLIDAY_TITLES = {
    "New Year's Day", "New Year's Eve",
    "Martin Luther King Jr. Day", "Presidents' Day", "Valentine's Day",
    "St. Patrick's Day", "Good Friday", "Easter", "Easter Sunday",
    "Cinco de Mayo", "Mother's Day", "Memorial Day", "Father's Day",
    "Juneteenth", "Independence Day", "Labor Day", "Columbus Day",
    "Indigenous Peoples' Day", "Halloween", "Veterans Day", "Thanksgiving",
    "Christmas Eve", "Christmas", "Boxing Day", "Groundhog Day",
    "April Fools' Day", "Earth Day", "Bastille Day", "Guy Fawkes Night",
    "Diwali", "Hanukkah", "Eid al-Fitr", "Eid al-Adha",
    "Chinese New Year", "Lunar New Year",
}


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

        if article.title in HOLIDAY_TITLES or article.normalized_title in HOLIDAY_TITLES:
            return self._enrich_holiday_article(article)

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

    def _enrich_holiday_article(self, article: Article) -> Article:
        """Special-case handler for recurring calendar holidays (HOLIDAY_TITLES):
        skip search entirely -- there's rarely a real news story behind why a
        holiday trends, it's just the date itself, so search has nothing
        reliable to find. For holidays with a known Nth-weekday-of-month
        schedule rule (describe_holiday_date), the rule and this year's
        earliest/latest-possible framing are handed to the LLM as optional
        context rather than forced into the reason -- most occurrences land
        in the unremarkable middle of the range, so the model only mentions
        it when it's actually a notable edge case. Fixed-date and
        lunar/lunisolar holidays (describe_holiday_date returns None) get no
        schedule context at all, same as before."""
        title = article.normalized_title or article.title
        target_date = datetime.strptime(article.date, "%Y-%m-%d").date()
        info = describe_holiday_date(title, target_date)

        if info:
            schedule_fact_block = (
                f"Schedule fact (mention only if genuinely interesting): {title} falls on "
                f"{info['rule_phrase']} each year. This year that's {info['date_phrase']}, "
                f"{info['extremity_phrase']}.\n\n"
            )
        else:
            schedule_fact_block = ""

        prompt = HOLIDAY_EXPLANATION_PROMPT.format(
            title=title,
            schedule_fact_block=schedule_fact_block,
            summary=article.summary or article.extract[:200],
        )
        article.trending_reason = self.llm_client.generate(
            prompt=prompt,
            model=HOLIDAY_EXPLANATION_MODEL,
            temperature=HOLIDAY_EXPLANATION_TEMPERATURE,
            max_tokens=HOLIDAY_EXPLANATION_MAX_TOKENS,
        )

        short_prompt = SHORT_PROMPT.format(
            title=title,
            summary=article.summary or article.extract[:200],
            trending_reason=article.trending_reason,
        )
        article.trending_reason_short = self.llm_client.generate(
            prompt=short_prompt,
            model=SHORT_MODEL,
            temperature=SHORT_TEMPERATURE,
            max_tokens=SHORT_MAX_TOKENS,
        )

        article.trending_reason_source = "holiday"
        article.raw_search_results = ""
        article.search_query_used = ""
        article.is_mystery = False
        print(f"  [enricher] Holiday article — skipped search, LLM-composed reason for {title!r}")
        return article
