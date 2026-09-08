"""Date-math for recurring calendar holidays defined by an "Nth weekday of
month" rule (Labor Day = 1st Monday of September, Thanksgiving = 4th
Thursday of November, etc.) -- lets holiday content say something more
specific than "it's the holiday": which weekday-of-month rule governs it,
and whether this year's occurrence is the earliest/latest possible or
somewhere in between.

Holidays NOT defined by this kind of rule (fixed-date ones like Christmas,
lunar/lunisolar ones like Easter, Diwali, Hanukkah, Eid, Lunar New Year)
aren't included here -- there's no reliable schedule-rule computation for
them without a calendar-conversion dependency this project doesn't have,
and a wrong "earliest/latest" claim would be worse than no claim at all.
describe_holiday_date returns None for these; callers fall back to a
simpler, schedule-free description.
"""
import calendar
from datetime import date, datetime

# name -> (month, weekday [Mon=0..Sun=6], nth [1-4, or -1 for "last"])
NTH_WEEKDAY_HOLIDAYS = {
    "Martin Luther King Jr. Day": (1, 0, 3),
    "Presidents' Day": (2, 0, 3),
    "Mother's Day": (5, 6, 2),
    "Memorial Day": (5, 0, -1),
    "Father's Day": (6, 6, 3),
    "Labor Day": (9, 0, 1),
    "Columbus Day": (10, 0, 2),
    "Indigenous Peoples' Day": (10, 0, 2),
    "Thanksgiving": (11, 3, 4),
}

_ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}
_WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _nth_weekday_date(year: int, month: int, weekday: int, nth: int) -> date:
    weeks = calendar.monthcalendar(year, month)
    days = [week[weekday] for week in weeks if week[weekday] != 0]
    return date(year, month, days[nth - 1] if nth > 0 else days[nth])


def _day_of_month_range(month: int, weekday: int, nth: int) -> tuple[int, int]:
    """Earliest/latest possible day-of-month this rule can land on, found by
    brute force across a wide year window -- simpler and less error-prone
    than deriving the min/max analytically per rule shape (Nth vs "last")."""
    days = [_nth_weekday_date(y, month, weekday, nth).day for y in range(1901, 2101)]
    return min(days), max(days)


def _ordinal_suffix(day: int) -> str:
    if 11 <= day % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


def describe_holiday_date(title: str, target_date: date) -> dict | None:
    """Return {rule_phrase, extremity_phrase, date_phrase} for a holiday with
    a known Nth-weekday-of-month rule, or None if `title` isn't one (fixed-date
    and lunar/lunisolar holidays -- see module docstring)."""
    rule = NTH_WEEKDAY_HOLIDAYS.get(title)
    if rule is None:
        return None
    month, weekday, nth = rule

    lo, hi = _day_of_month_range(month, weekday, nth)
    day = target_date.day

    if day == hi:
        extremity_phrase = "the latest it could be"
    elif day == lo:
        extremity_phrase = "the earliest it could be"
    else:
        dist_to_hi, dist_to_lo = hi - day, day - lo
        if dist_to_hi <= dist_to_lo:
            n = dist_to_hi
            extremity_phrase = f"{n} day{'s' if n != 1 else ''} before the latest it could be"
        else:
            n = dist_to_lo
            extremity_phrase = f"{n} day{'s' if n != 1 else ''} after the earliest it could be"

    ordinal = _ORDINALS.get(nth, str(nth))
    rule_phrase = f"the {ordinal} {_WEEKDAY_NAMES[weekday]} in {calendar.month_name[month]}"
    date_phrase = f"{calendar.month_name[month]} {day}{_ordinal_suffix(day)}"

    return {
        "rule_phrase": rule_phrase,
        "extremity_phrase": extremity_phrase,
        "date_phrase": date_phrase,
    }


def build_holiday_row(
    normalized_title: str,
    trending_date: str,
    summary: str,
    country: str | None = None,
    image_url: str | None = None,
) -> dict:
    """A daily_trend_rows row (category="holiday") for a recurring calendar
    holiday. Deterministic -- no LLM call here. `summary` is the article's own
    already-generated content-classification summary (see main.py's
    _generate_summary_and_classify), reused as the purpose/meaning component
    since it's already grounded in the Wikipedia extract -- this function
    only adds the deterministic schedule/date fact on top of it."""
    target_date = datetime.strptime(trending_date, "%Y-%m-%d").date()
    info = describe_holiday_date(normalized_title, target_date)
    purpose = (summary or normalized_title).rstrip(". ")

    if info:
        row_summary = f"{purpose}, fell on {info['date_phrase']} this year -- {info['extremity_phrase']}."
    else:
        row_summary = f"{purpose}. Observed today, {target_date.strftime('%B')} {target_date.day}."

    return {
        "category": "holiday",
        "titles": [normalized_title],
        "headline": normalized_title,
        "summary": row_summary,
        "image_url": image_url,
        "topic": "holiday",
        "country": country,
        "is_mystery": False,
        "streak_days": None,
        "trajectory": None,
    }
