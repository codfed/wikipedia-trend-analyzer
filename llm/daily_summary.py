"""Generate structured daily-trend rows (not narrative prose) from per-article
reasons + TrendStats.

Every new trend gets its own scannable one-line row; only articles sharing
the same real-world story or event get pulled into a single cluster row with
one synthesized blurb. Continuing trends don't get rows yet. One LLM call
per date -- spotting which new articles share a story requires seeing the
whole day's list at once.
"""
from pipeline.daily_stats import TrendStats, CATEGORY_BOT_TRAFFIC
from llm.client import LLMClient
from llm.prompts import (
    DAILY_SUMMARY_MODEL,
    DAILY_SUMMARY_TEMPERATURE,
    DAILY_SUMMARY_MAX_TOKENS,
    DAILY_SUMMARY_PROMPT,
)

CATEGORY_NEW = "new"
CATEGORY_NEW_CLUSTER = "new_cluster"


class DailySummaryGenerator:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def generate(
        self,
        target_date: str,
        articles: list[dict],
        stats: dict[str, TrendStats],
    ) -> list[dict]:
        """Return row dicts ready to insert into `daily_trend_rows`:
        {category, titles, headline, summary, streak_days, trajectory}.

        `articles` is a list of dicts with at least `normalized_title` and
        `trending_reason` (or `trending_reason_short`) keys. Continuing
        articles and BOT_TRAFFIC_TITLES are dropped entirely -- no rows yet.
        """
        new_block_lines = []
        eligible_titles: set[str] = set()
        reasons_by_title: dict[str, str] = {}

        for article in articles:
            title = article["normalized_title"]
            s = stats.get(title)
            if s is None or not s.is_new or s.category == CATEGORY_BOT_TRAFFIC:
                continue

            reason = (
                article.get("trending_reason")
                or article.get("trending_reason_short")
                or "(no reason found)"
            )
            new_block_lines.append(f"- {title}: {reason}")
            eligible_titles.add(title)
            reasons_by_title[title] = reason

        if not eligible_titles:
            return []

        prompt = DAILY_SUMMARY_PROMPT.format(new_articles_block="\n".join(new_block_lines))
        data = self.llm_client.generate_json(
            prompt=prompt,
            model=DAILY_SUMMARY_MODEL,
            temperature=DAILY_SUMMARY_TEMPERATURE,
            max_tokens=DAILY_SUMMARY_MAX_TOKENS,
        )

        rows: list[dict] = []
        claimed: set[str] = set()

        for row in data.get("rows", []):
            # Defensive filter: only titles we actually sent qualify, and
            # each title can only be claimed by the first row that names it.
            titles = [t for t in (row.get("titles") or []) if t in eligible_titles and t not in claimed]
            if not titles:
                continue
            claimed.update(titles)
            rows.append({
                "category": CATEGORY_NEW if len(titles) == 1 else CATEGORY_NEW_CLUSTER,
                "titles": titles,
                "headline": row.get("headline", ""),
                "summary": row.get("summary", ""),
                "streak_days": None,
                "trajectory": None,
            })

        # Safety net: the model can drop a title on the floor entirely --
        # never let an article vanish from the digest. Fall back to its own
        # reason text as the blurb and the raw title as the headline.
        for title in sorted(eligible_titles - claimed):
            rows.append({
                "category": CATEGORY_NEW,
                "titles": [title],
                "headline": title,
                "summary": reasons_by_title[title],
                "streak_days": None,
                "trajectory": None,
            })

        return rows
