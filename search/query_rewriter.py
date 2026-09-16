"""LLM-based query rewriter for Stage 3 deep search."""
from pipeline.models import Article
from llm.client import LLMClient


REWRITE_MODEL = "claude-haiku-4-5-20251001"
REWRITE_TEMPERATURE = 0.3
REWRITE_MAX_TOKENS = 32


def rewrite_query(article: Article, llm_client: LLMClient) -> str:
    """Generate a 4-6 word search query to explain unexpected Wikipedia traffic.

    Unlike stages 1-4, which search the article's exact title, this stage
    needs the LLM to guess a *different, more specific* query -- so it needs
    real context to guess well, not the bare title alone. A title-only guess
    for a broad subject (e.g. "2014 European Parliament election") produces
    generic noise, because the actual driver is often something adjacent to
    the article's subject rather than the subject itself -- observed missing
    a real case: a viral repost of a 2014 speech by two MEPs who were first
    elected in that election, resurfacing right around its 12-year
    anniversary, amplified by unrelated current news about the same people.
    The article's own summary is what lets the model guess at that kind of
    adjacent-but-connected driver instead of restating the title back.

    Returns a plain string suitable for use as a Serper query.
    """
    prompt = (
        f"No relevant news, web, or reddit results were found for this Wikipedia article, "
        f"which is unexpectedly trending. Generate a 4-6 word search query that might explain "
        f"why, using the summary below for context.\n\n"
        f"Consider non-news drivers: a viral video, podcast episode, forum discussion, meme, or "
        f"online community post. Also consider a specific quote, decision, incident, or person "
        f"CONNECTED TO this subject (not necessarily the subject itself) that recently "
        f"resurfaced on social media -- especially if today is near the anniversary of that "
        f"specific incident, since old quotes and clips often go viral again around their "
        f"anniversary, amplified by current, unrelated news about the same people or topic.\n\n"
        f"Output ONLY the query, nothing else.\n\n"
        f"Article title: {article.normalized_title}\n"
        f"Article summary: {article.summary or article.extract[:200]}"
    )
    result = llm_client.generate(
        prompt=prompt,
        model=REWRITE_MODEL,
        temperature=REWRITE_TEMPERATURE,
        max_tokens=REWRITE_MAX_TOKENS,
    )
    # Strip any surrounding quotes or punctuation the model might add
    return result.strip().strip('"\'').strip()
