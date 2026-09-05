"""Scrape deaths for a specific date from the Wikipedia 'Deaths in YYYY' article."""
import calendar
import os
import re

import requests

_WIKI_API = "https://en.wikipedia.org/w/api.php"
_TIMEOUT = 5  # seconds

DEATHS_ARTICLE_RE = re.compile(r"^Deaths[_ ]in[_ ](\d{4})$", re.IGNORECASE)


def build_obituary_row(normalized_title: str, entries: list[str], stats: dict | None = None) -> dict:
    """A daily_trend_rows row for a 'Deaths in YYYY' article's entries for one
    date. Deterministic -- no LLM involved, this is a verbatim slice of
    Wikipedia's own list. `stats` is the dict of TrendStats keyed by
    normalized_title returned by pipeline.daily_stats.compute_daily_stats;
    pass None if unavailable and streak_days/trajectory are left null."""
    s = (stats or {}).get(normalized_title)
    return {
        "category": "ongoing_list",
        "titles": [normalized_title],
        "headline": normalized_title,
        "summary": "\n".join(f"• {e}" for e in entries),
        "image_url": None,
        "streak_days": s.streak_days if s else None,
        "trajectory": s.trajectory if s else None,
    }


def _make_session() -> requests.Session:
    email = os.environ.get("WIKIPEDIA_EMAIL", "")
    contact = f"; mailto:{email}" if email else ""
    session = requests.Session()
    session.headers.update({
        "User-Agent": f"wikipedia-trend-analyzer/2.0 (https://github.com/wikipedia-trend-analyzer{contact})"
    })
    return session


def scrape_deaths_for_date(year: int, month: int, day: int) -> tuple[list[str], str]:
    """Fetch the 'Deaths in {year}' Wikipedia article and return entries for the given date.

    Returns:
        (entries, raw_section) where entries is a list of cleaned plain-text death
        descriptions and raw_section is the raw wikitext around that day (for debug/evals).
        Returns ([], "") on any network or parse failure.
    """
    try:
        return _fetch_and_parse(year, month, day)
    except Exception as e:
        print(f"  [deaths_scraper] Failed to scrape Deaths_in_{year}: {e}")
        return [], ""


def _fetch_and_parse(year: int, month: int, day: int) -> tuple[list[str], str]:
    session = _make_session()
    resp = session.get(
        _WIKI_API,
        params={
            "action": "parse",
            "page": f"Deaths in {year}",
            "prop": "wikitext",
            "format": "json",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    wikitext = resp.json()["parse"]["wikitext"]["*"]
    entries, raw_section = _extract_entries(wikitext, month, day)
    return entries, raw_section


def _extract_entries(wikitext: str, month: int, day: int) -> tuple[list[str], str]:
    """Parse wikitext to extract death entries for the given month/day."""
    month_name = calendar.month_name[month]

    # Find the start of the month section (==April== or == April ==)
    month_pattern = re.compile(
        r'^==\s*' + re.escape(month_name) + r'\s*==\s*$', re.MULTILINE
    )
    month_match = month_pattern.search(wikitext)
    if not month_match:
        return [], ""

    # Slice to just this month's content (up to the next == heading)
    month_start = month_match.end()
    next_month = re.search(r'^==\s*\w', wikitext[month_start:], re.MULTILINE)
    month_section = (
        wikitext[month_start: month_start + next_month.start()]
        if next_month
        else wikitext[month_start:]
    )

    # Find the day subheading (===15=== or === 15 ===)
    day_pattern = re.compile(
        r'^===\s*' + str(day) + r'\s*===\s*$', re.MULTILINE
    )
    day_match = day_pattern.search(month_section)
    if not day_match:
        return [], ""

    # Slice to just this day's content (up to the next === or == heading)
    day_start = day_match.end()
    next_heading = re.search(r'^===', month_section[day_start:], re.MULTILINE)
    day_section = (
        month_section[day_start: day_start + next_heading.start()]
        if next_heading
        else month_section[day_start:]
    )

    # Extract bullet entries and clean markup
    entries = []
    for line in day_section.splitlines():
        stripped = line.strip()
        if not stripped.startswith('*'):
            continue
        cleaned = _clean_wikitext(stripped.lstrip('*').strip())
        if cleaned:
            entries.append(cleaned)

    return entries, day_section.strip()


def _clean_wikitext(text: str) -> str:
    """Convert wikitext markup to plain text with markdown links."""
    # [[Article|Display]] → [Display](wiki url)
    # [[Article]] → [Article](wiki url)
    def _wiki_link(m: re.Match) -> str:
        parts = m.group(1).split("|", 1)
        article = parts[0].strip()
        display = parts[1].strip() if len(parts) == 2 else article
        url = "https://en.wikipedia.org/wiki/" + article.replace(" ", "_")
        return f"[{display}]({url})"

    # <ref>...</ref> and self-closing <ref .../> citations → remove entirely
    # (must run before the [[link]] pass -- ref content often embeds its own
    # [url text] / [[wiki links]] that would otherwise leak through)
    text = re.sub(r'<ref[^>]*/>', '', text)
    text = re.sub(r'<ref[^>]*>.*?</ref>', '', text, flags=re.DOTALL)

    text = re.sub(r'\[\[([^\]]+)\]\]', _wiki_link, text)
    # {{template|...}} → remove entirely
    text = re.sub(r'\{\{[^}]*\}\}', '', text)
    # [1] footnote references → remove
    text = re.sub(r'\[\d+\]', '', text)
    # '''bold''' and ''italic'' → plain text
    text = text.replace("'''", '').replace("''", '')
    return re.sub(r'\s+', ' ', text).strip()
