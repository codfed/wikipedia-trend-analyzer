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


def check_word_count(text: str, min_words: int, max_words: int) -> MetricResult:
    count = len(text.split())
    passed = min_words <= count <= max_words
    return MetricResult(
        check="word_count",
        passed=passed,
        detail=f"{count} words (expected {min_words}–{max_words})",
    )


def check_no_title_mention(text: str, title: str) -> MetricResult:
    passed = title.lower() not in text.lower()
    return MetricResult(
        check="no_title_mention",
        passed=passed,
        detail="OK" if passed else f"Title '{title}' found in output",
    )


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

    # trending_reason: loose sentence-count heuristic (aligned with ~1–3 short sentences)
    sentence_count = article.trending_reason.count(".") + article.trending_reason.count("!") + article.trending_reason.count("?")
    results.append(MetricResult(
        check="trending_reason_sentence_count",
        passed=1 <= sentence_count <= 5,
        detail=f"~{sentence_count} sentence boundaries (expected about 1–3)",
    ))
    results.append(check_banned_phrases(article.trending_reason))

    # trending_reason_short: no title (word count not enforced — LLM judge handles conciseness)
    results.append(check_no_title_mention(article.trending_reason_short, article.title))
    results.append(check_no_title_mention(article.trending_reason_short, article.normalized_title))

    return results
