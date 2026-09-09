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
from datetime import date

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
    and lunar/lunisolar holidays -- see module docstring) or if target_date's
    day-of-month falls outside the rule's valid range entirely. The latter
    happens when Wikipedia traffic for the holiday spills into a second day
    (e.g. "Labor Day" still trending the day after the actual Monday) --
    target_date is then a day removed from any real occurrence of the rule,
    so no earliest/latest claim can be made; treat it like the no-rule case
    rather than let the day-8-vs-range-[1,7] math produce a negative "n"."""
    rule = NTH_WEEKDAY_HOLIDAYS.get(title)
    if rule is None:
        return None
    month, weekday, nth = rule

    lo, hi = _day_of_month_range(month, weekday, nth)
    day = target_date.day
    if not (lo <= day <= hi):
        return None

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
