"""Shared content-classification taxonomy: what an article is ABOUT, not
why it's trending. Classified once per article (see main.py's per-article
summary step) from title+extract alone, so it works even for is_mystery
articles where the trending reason itself is never known.

Used downstream by llm/daily_summary.py, which copies a digest row's
topic/country from its subject article rather than classifying independently.
"""
import re

DEFAULT_TOPIC = "other"

# Must stay in sync with the grouped, human-readable list in
# CLASSIFY_PROMPT (llm/prompts.py) -- that's what's shown to the model;
# this is the enforcement copy. A topic the model returns that isn't in
# this set is replaced with DEFAULT_TOPIC rather than trusted verbatim.
VALID_TOPICS = {
    # Sports
    "soccer", "american_football", "basketball", "baseball", "tennis", "golf",
    "boxing", "mma", "hockey", "cricket", "rugby", "skiing", "swimming",
    "athletics", "cycling", "motorsport", "esports", "sport_other",
    # Entertainment media
    "movie", "tv_show", "book", "video_game",
    "music_rock", "music_pop", "music_classical", "music_hiphop", "music_country", "music_other",
    # People by role
    "actor", "comedian", "tv_anchor", "musician", "author", "politician",
    "business_executive", "religious_figure", "royal",
    # Crime & justice
    "crime_violent", "crime_white_collar", "legal_verdict",
    # World & science
    "politics_world", "science_tech", "space", "health_medicine",
    # Other
    "death", "religion_culture", "natural_disaster", "weird", DEFAULT_TOPIC,
}

_COUNTRY_CODE_RE = re.compile(r"^[A-Z]{2}$")


def clean_topic(value) -> str:
    return value if value in VALID_TOPICS else DEFAULT_TOPIC


def clean_country(value) -> str | None:
    return value if isinstance(value, str) and _COUNTRY_CODE_RE.match(value) else None
