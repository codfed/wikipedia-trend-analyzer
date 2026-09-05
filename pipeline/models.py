"""Article dataclass — single source of truth for the v2 pipeline."""
import json
from dataclasses import dataclass, field, fields
from typing import Any, Optional


@dataclass
class Article:
    # Core identity
    date: str
    title: str
    normalized_title: str

    # Feed data
    view_count: int = 0
    rank: int = 0
    mystery_rank: int = 0
    link: str = ""
    thumbnail: Optional[str] = None
    extract: str = ""
    view_history: Any = field(default_factory=list)

    # Trending analysis
    is_newly_trending: bool = False
    view_delta_percentage: int = 0

    # LLM-generated description (always runs)
    summary: str = ""

    # Unified explanation fields (replaces news_relation / search_relation / *_short)
    trending_reason: str = ""
    trending_reason_short: str = ""
    trending_reason_source: str = "unknown"  # "news"|"search"|"reddit"|"deep_search"|"unknown"

    # Mystery flag — set when all search stages fail
    is_mystery: bool = False

    # Raw data snapshot used to produce the explanation (stored for evals)
    raw_search_results: str = ""
    search_query_used: str = ""

    # Set when trending_reason is carried forward from a prior day's row
    carried_from_date: Optional[str] = None

    # Structured per-day entries scraped for "Deaths in YYYY" rolling-list
    # articles (see pipeline/deaths_scraper.py) -- empty for every other article
    death_entries: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def pretty_print(self) -> None:
        d = self.to_dict()
        width = max(len(k) for k in d)
        for key, value in d.items():
            print(f"{key:<{width}} : {str(value)[:90]}")

    def to_json(self, **kwargs) -> str:
        return json.dumps(self.to_dict(), **kwargs)
