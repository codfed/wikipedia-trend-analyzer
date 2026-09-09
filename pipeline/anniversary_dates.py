"""Date-math for anniversary lead-up detection: given a candidate "MM-DD"
association (from LLM world knowledge, see pipeline/anniversary.py) and the
article's trending_date, decide whether that date falls within the lead-up
window and describe it in words.

Deliberately forward-looking only -- an anniversary that already passed this
year, even by a day, is not a match; the window exists to catch articles
trending *ahead of* a date, matching the observed pattern (e.g. "Falling
Man" spiking days before September 11, not after). No "Nth anniversary"
claim is made here since the LLM's guess at an exact origin year isn't
grounded the way the search-verification step (pipeline/anniversary.py)
grounds the event association itself -- if a year is worth stating, it
should come from the grounding search results, not from this module.
"""
import calendar
from datetime import date

LEAD_UP_WINDOW_DAYS = 7

_ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _ordinal_suffix(day: int) -> str:
    if 11 <= day % 100 <= 13:
        return "th"
    return _ORDINAL_SUFFIX.get(day % 10, "th")


def describe_anniversary_proximity(month_day: str, target_date: date) -> dict | None:
    """`month_day` is an "MM-DD" string. Returns {days_until, date_phrase,
    weekday_phrase} for the next occurrence of that month/day if it falls
    within LEAD_UP_WINDOW_DAYS of target_date (0 = today), else None.
    """
    try:
        month_str, day_str = month_day.split("-")
        month, day = int(month_str), int(day_str)
        if not (1 <= month <= 12):
            return None
    except (ValueError, AttributeError):
        return None

    for year in (target_date.year, target_date.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            continue  # e.g. Feb 29 in a non-leap year
        days_until = (candidate - target_date).days
        if 0 <= days_until <= LEAD_UP_WINDOW_DAYS:
            return {
                "days_until": days_until,
                "date_phrase": f"{calendar.month_name[month]} {day}{_ordinal_suffix(day)}",
                "weekday_phrase": candidate.strftime("%A"),
            }

    return None
