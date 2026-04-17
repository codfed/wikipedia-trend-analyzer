"""Deterministic checks that run before LLM judging."""
from dataclasses import dataclass
from pipeline.models import Article

BANNED_PHRASES = [
    "here is the reason why",
    "the article is trending because",
    "spotlight",
    "widespread",
]


@dataclass
class MetricResult:
    check: str
    passed: bool
    detail: str



def check_banned_phrases(text: str) -> MetricResult:
    lower = text.lower()
    found = [p for p in BANNED_PHRASES if p in lower]
    passed = len(found) == 0
    return MetricResult(
        check="banned_phrases",
        passed=passed,
        detail="OK" if passed else f"Found: {found}",
    )


def run_deterministic_checks(article: Article) -> list[MetricResult]:
    """Run all deterministic checks on an article's generated fields."""
    if article.trending_reason_source in ("rolling_list", "carried_forward"):
        label = article.trending_reason_source
        return [MetricResult(
            check=label,
            passed=True,
            detail=f"{label} article — deterministic checks skipped",
        )]

    results = []

    results.append(check_banned_phrases(article.trending_reason))

    return results
