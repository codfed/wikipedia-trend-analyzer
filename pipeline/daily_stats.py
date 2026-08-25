"""Compute cross-trend stats for the daily summary: streaks and trajectories.

Deterministic, DB-driven -- no LLM involved. `trending_articles_v2` already
stores one row per (title, trending_date) with `view_delta_percentage`
computed at save time, so a trend's history is just its rows walked
backward from the target date until the first calendar-day gap.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from db.client import SupabaseClient

ARTICLE_TABLE = "trending_articles_v2"

# How far back a streak can be walked. Longer than this and trajectory is
# computed from just the most recent window rather than the full history.
LOOKBACK_DAYS = 14

# view_delta_percentage swing (in percentage points) needed to call a
# trend's trajectory accelerating/declining rather than plateauing.
TRAJECTORY_THRESHOLD = 10

CATEGORY_ORGANIC = "organic"
CATEGORY_BOT_TRAFFIC = "bot_traffic"

# Titles that persistently trend from automated/bot traffic rather than
# organic reader interest -- generic domain-name-style titles and obscure
# geography stubs are the recurring pattern. Wikipedia's pageview feed
# doesn't filter this out, and it shows up as long streaks with noisy,
# directionless view-delta swings and no real external driver. There's no
# reliable numeric signature to detect this automatically (e.g. Google has
# the same noisy pattern but is also genuinely newsworthy most days), so
# this is a hand-maintained list -- add to it as new offenders are spotted.
BOT_TRAFFIC_TITLES = {
    "Google",
    "Neatsville, Kentucky",
    ".xyz",
    ".xxx",
}


@dataclass
class TrendStats:
    normalized_title: str
    streak_days: int  # consecutive days through target_date, including it
    view_delta_history: list[int]  # oldest -> newest
    trajectory: str  # "new" | "accelerating" | "declining" | "plateauing"
    is_new: bool
    category: str  # "organic" | "bot_traffic"


def _trajectory(deltas: list[int]) -> str:
    if len(deltas) < 2:
        return "new"
    recent, prior = deltas[-1], deltas[-2]
    if recent > prior + TRAJECTORY_THRESHOLD:
        return "accelerating"
    if recent < prior - TRAJECTORY_THRESHOLD:
        return "declining"
    return "plateauing"


def compute_daily_stats(
    supabase_client: SupabaseClient,
    target_date: str,
    normalized_titles: list[str],
) -> dict[str, TrendStats]:
    """Streak + trajectory for each title trending on target_date.

    Walks each title's rows backward from target_date and stops at the
    first missing calendar day, so a title that drops out and later
    re-enters the feed starts a fresh streak rather than resuming the old
    one.
    """
    if not normalized_titles:
        return {}

    db = supabase_client.client
    cutoff = (date.fromisoformat(target_date) - timedelta(days=LOOKBACK_DAYS)).isoformat()

    rows = (
        db.table(ARTICLE_TABLE)
        .select("normalized_title,trending_date,view_delta_percentage")
        .in_("normalized_title", normalized_titles)
        .gte("trending_date", cutoff)
        .lte("trending_date", target_date)
        .execute()
    ).data

    by_title: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_title[row["normalized_title"]].append(row)

    stats: dict[str, TrendStats] = {}
    for title in normalized_titles:
        day_rows = sorted(
            by_title.get(title, []), key=lambda r: r["trending_date"], reverse=True
        )

        streak: list[int] = []
        expected = date.fromisoformat(target_date)
        for row in day_rows:
            if row["trending_date"] != expected.isoformat():
                break
            streak.append(row["view_delta_percentage"] or 0)
            expected -= timedelta(days=1)
        streak.reverse()

        stats[title] = TrendStats(
            normalized_title=title,
            streak_days=len(streak),
            view_delta_history=streak,
            trajectory=_trajectory(streak),
            is_new=len(streak) <= 1,
            category=CATEGORY_BOT_TRAFFIC if title in BOT_TRAFFIC_TITLES else CATEGORY_ORGANIC,
        )

    return stats
