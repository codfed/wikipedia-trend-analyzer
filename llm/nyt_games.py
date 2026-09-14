"""Shared keyword detection for NYT daily puzzle content (Connections,
Wordle, Spelling Bee, Strands).

Used in two places that need the same answer to "is this NYT-puzzle-driven"
but look at different text:
- llm/generator.py checks raw search RESULTS, to decide whether to inject
  NYT_GAMES_LENGTH_RULE/NYT_GAMES_ACCURACY_NOTE (see llm/prompts.py) --
  content can surface this under any tiered-search stage, not just the
  dedicated "nyt_games" one (a plain "search"-stage query can incidentally
  turn up Connections coverage, as happened for Garfield/Odie).
- llm/daily_summary.py checks the final, already-generated trending_reason
  text, to decide whether a digest row gets topic="puzzle" (see
  llm/topics.py) -- this relies on NYT_GAMES_LENGTH_RULE/_ACCURACY_NOTE's
  own requirement that the explanation name the specific puzzle by name
  ("NYT Connections", "NYT Wordle", etc.), so the final reason text is a
  reliable enough signal without needing a dedicated DB column.
"""

NYT_GAMES_KEYWORDS = (
    "nytconnections",
    "nyt connections",
    "connections puzzle",
    "nyt wordle",
    "wordle answer",
    "nyt spelling bee",
    "nyt strands",
)


def mentions_nyt_games(text: str) -> bool:
    lower = (text or "").lower()
    return any(kw in lower for kw in NYT_GAMES_KEYWORDS)
