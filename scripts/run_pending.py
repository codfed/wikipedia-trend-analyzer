"""CI entry point: backfill every date since the pipeline started that
doesn't have saved articles yet, instead of relying on same-day cron retries.

If a date's featured feed isn't published yet (missing 'mostread'), that
date is skipped for this run and picked up automatically once a future run
still finds it missing -- no separate retry schedule needed.

A cap limits how many dates a single invocation will backfill, so a long
outage doesn't turn one run into a multi-week reprocessing job. Override
with MAX_BACKFILL_DATES.
"""
import os
import subprocess
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

load_dotenv()

from db.client import SupabaseClient

ARTICLE_TABLE = "trending_articles_v2"

# The pipeline has no meaningful data before this date -- never backfill
# earlier than this, even if it shows up as "missing".
EARLIEST_DATE = date(2026, 4, 11)

MAX_DATES_PER_RUN = int(os.getenv("MAX_BACKFILL_DATES", "5"))

MOSTREAD_NOT_READY_MARKER = "missing the 'mostread' section"


def missing_dates() -> list[date]:
    db = SupabaseClient().client
    result = db.table(ARTICLE_TABLE).select("trending_date").execute()
    have = {row["trending_date"] for row in result.data}

    dates = []
    d = EARLIEST_DATE
    today = date.today()
    while d <= today:
        if d.isoformat() not in have:
            dates.append(d)
        d += timedelta(days=1)
    return dates


def main() -> int:
    pending = missing_dates()
    if not pending:
        print("No missing dates -- nothing to do.")
        return 0

    todo = pending[:MAX_DATES_PER_RUN]
    if len(pending) > len(todo):
        print(
            f"{len(pending)} dates missing; processing the oldest {len(todo)} "
            f"this run: {[d.isoformat() for d in todo]}"
        )
    else:
        print(f"Processing {len(todo)} missing date(s): {[d.isoformat() for d in todo]}")

    failures = []
    for d in todo:
        print(f"\n=== {d.isoformat()} ===")
        env = {**os.environ, "TARGET_DATE": d.isoformat()}
        proc = subprocess.run(
            [sys.executable, "main.py"], env=env, capture_output=True, text=True
        )
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        if proc.returncode != 0:
            if MOSTREAD_NOT_READY_MARKER in proc.stderr:
                print(f"{d.isoformat()}: featured feed not published yet -- will retry on a future run.")
                continue
            failures.append(d.isoformat())

    if failures:
        print(f"\nFailed dates: {failures}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
