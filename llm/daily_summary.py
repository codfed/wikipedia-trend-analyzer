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
from llm.topics import DEFAULT_TOPIC
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
        {category, titles, headline, summary, image_url, topic, country,
        is_mystery, streak_days, trajectory}.

        `articles` is a list of dicts with at least `normalized_title`,
        `thumbnail`, `topic`, `country`, `is_mystery`, and `trending_reason`
        (or `trending_reason_short`) keys -- topic/country/is_mystery are
        classified once per article (see main.py's summary step, llm/topics.py)
        and just looked up here per row's subject_title, not re-judged.
        Continuing articles and BOT_TRAFFIC_TITLES are dropped entirely --
        no rows yet. Purely domestic Indian stories with no worldwide
        significance are also dropped (model judgment, see
        DAILY_SUMMARY_PROMPT step 7).
        """
        new_block_lines = []
        eligible_titles: set[str] = set()
        reasons_by_title: dict[str, str] = {}
        thumbnails_by_title: dict[str, str] = {}
        topics_by_title: dict[str, str] = {}
        countries_by_title: dict[str, str] = {}
        mystery_by_title: dict[str, bool] = {}

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
            if article.get("thumbnail"):
                thumbnails_by_title[title] = article["thumbnail"]
            topics_by_title[title] = article.get("topic") or DEFAULT_TOPIC
            countries_by_title[title] = article.get("country")
            mystery_by_title[title] = bool(article.get("is_mystery"))

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

        # Titles the model judged as purely domestic Indian stories with no
        # worldwide significance (see DAILY_SUMMARY_PROMPT step 7). Claimed
        # up front, before any row is built, so they can't slip into a row
        # (model error) and so the safety-net pass below -- which exists to
        # catch titles the model drops *unintentionally* -- doesn't undo an
        # intentional exclusion by treating it as an accident.
        excluded_india_local = set(data.get("excluded_india_local") or []) & eligible_titles
        claimed.update(excluded_india_local)

        for row in data.get("rows", []):
            # Defensive filter: only titles we actually sent qualify, and
            # each title can only be claimed by the first row that names it.
            titles = [t for t in (row.get("titles") or []) if t in eligible_titles and t not in claimed]
            if not titles:
                continue
            claimed.update(titles)
            is_cluster = len(titles) > 1

            subject_title = row.get("subject_title")
            if subject_title not in titles:
                subject_title = titles[0]

            # Clusters always get an image when the subject has a thumbnail
            # (a "cover story" deserves one whenever the data allows it).
            # Standalone entries only get one when the model flagged real
            # visual/narrative novelty -- most routine news stays image-free.
            image_worthy = is_cluster or bool(row.get("image_worthy"))
            image_url = thumbnails_by_title.get(subject_title) if image_worthy else None

            # topic/country/is_mystery are the subject article's own
            # classification (see llm/topics.py), not re-judged here --
            # EXCEPT is_death, which overrides topic to "death" regardless
            # of the subject's profession, since a per-article classification
            # from title+extract alone can never know "this person died
            # today" (see DAILY_SUMMARY_PROMPT step 8).
            topic = "death" if row.get("is_death") else topics_by_title.get(subject_title, DEFAULT_TOPIC)

            rows.append({
                "category": CATEGORY_NEW_CLUSTER if is_cluster else CATEGORY_NEW,
                "titles": titles,
                "headline": row.get("headline", ""),
                "summary": row.get("summary", ""),
                "image_url": image_url,
                "topic": topic,
                "country": countries_by_title.get(subject_title),
                "is_mystery": mystery_by_title.get(subject_title, False),
                "streak_days": None,
                "trajectory": None,
            })

        # Safety net: the model can drop a title on the floor by accident --
        # never let an article vanish from the digest that way. Deliberate
        # exclusions (excluded_india_local, above) are already in `claimed`
        # so they don't land here. Fall back to its own reason text as the
        # blurb and the raw title as the headline. No image and no is_death
        # override (there's no model judgment at all for these), but
        # topic/country/is_mystery still come from the article's own
        # classification since that's independent of the digest LLM call.
        for title in sorted(eligible_titles - claimed):
            rows.append({
                "category": CATEGORY_NEW,
                "titles": [title],
                "headline": title,
                "summary": reasons_by_title[title],
                "image_url": None,
                "topic": topics_by_title.get(title, DEFAULT_TOPIC),
                "country": countries_by_title.get(title),
                "is_mystery": mystery_by_title.get(title, False),
                "streak_days": None,
                "trajectory": None,
            })

        return rows
