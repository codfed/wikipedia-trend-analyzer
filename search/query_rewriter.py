"""LLM-based query rewriter for Stage 3 deep search."""
from pipeline.models import Article
from llm.client import LLMClient


REWRITE_MODEL = "claude-haiku-4-5-20251001"
REWRITE_TEMPERATURE = 0.3
REWRITE_MAX_TOKENS = 32


def rewrite_query(article: Article, llm_client: LLMClient) -> str:
    """Generate a 4-6 word search query to explain unexpected Wikipedia traffic.

    Returns a plain string suitable for use as a Serper query.
    """
    prompt = (
        f"Given this Wikipedia article title and the fact that no relevant news, web, "
        f"or reddit results were found, generate a 4-6 word search query that might "
        f"explain why it is suddenly getting traffic. Consider non-news drivers too — "
        f"a viral video, podcast episode, forum discussion, meme, or online community "
        f"post can all cause a traffic spike. Output ONLY the query, nothing else.\n\n"
        f"Article title: {article.normalized_title}"
    )
    result = llm_client.generate(
        prompt=prompt,
        model=REWRITE_MODEL,
        temperature=REWRITE_TEMPERATURE,
        max_tokens=REWRITE_MAX_TOKENS,
    )
    # Strip any surrounding quotes or punctuation the model might add
    return result.strip().strip('"\'').strip()
