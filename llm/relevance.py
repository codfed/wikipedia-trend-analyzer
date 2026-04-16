"""Structured relevance gate — returns (relevant: bool, confidence: float)."""
from pipeline.models import Article
from llm.client import LLMClient
from llm.prompts import (
    RELEVANCE_MODEL,
    RELEVANCE_TEMPERATURE,
    RELEVANCE_MAX_TOKENS,
    RELEVANCE_PROMPT,
)


def is_relevant(
    article: Article,
    formatted_results: str,
    llm_client: LLMClient,
) -> tuple[bool, float]:
    """Call the LLM to decide if search results explain why an article is trending.

    Returns:
        (relevant, confidence) where confidence is 0.0–1.0.
        On any parse failure, returns (False, 0.0).
    """
    prompt = RELEVANCE_PROMPT.format(
        title=article.normalized_title,
        summary=article.summary or article.extract[:200],
        results=formatted_results[:3000],  # cap to avoid prompt bloat
    )
    try:
        data = llm_client.generate_json(
            prompt=prompt,
            model=RELEVANCE_MODEL,
            temperature=RELEVANCE_TEMPERATURE,
            max_tokens=RELEVANCE_MAX_TOKENS,
        )
        relevant = bool(data.get("relevant", False))
        confidence = float(data.get("confidence", 0.0))
        return relevant, confidence
    except Exception as e:
        print(f"  [relevance] parse error: {e}")
        return False, 0.0
