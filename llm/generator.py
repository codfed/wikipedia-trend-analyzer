"""Generate trending_reason + trending_reason_short, injecting few-shot examples."""
import re

from pipeline.models import Article
from search.tiered import SearchResult
from llm.client import LLMClient
from llm.prompts import (
    EXPLANATION_MODEL,
    EXPLANATION_TEMPERATURE,
    EXPLANATION_MAX_TOKENS,
    EXPLANATION_PROMPT,
    DEFAULT_LENGTH_RULE,
    REDDIT_LENGTH_RULE,
    NYT_GAMES_LENGTH_RULE,
    NYT_GAMES_ACCURACY_NOTE,
    SHORT_MODEL,
    SHORT_TEMPERATURE,
    SHORT_MAX_TOKENS,
    SHORT_PROMPT,
)
from llm.nyt_games import mentions_nyt_games

_LENGTH_RULES_BY_STAGE = {
    "reddit": REDDIT_LENGTH_RULE,
    "nyt_games": NYT_GAMES_LENGTH_RULE,
}


class ExplanationGenerator:
    def __init__(self, llm_client: LLMClient, example_bank=None):
        """
        Args:
            llm_client: LLMClient instance.
            example_bank: Optional ExampleBank instance.  If None, no few-shot
                          examples are injected.
        """
        self.llm_client = llm_client
        self.example_bank = example_bank

    def generate(
        self, article: Article, search_result: SearchResult
    ) -> tuple[str, str]:
        """Return (trending_reason, trending_reason_short)."""
        few_shot_block = self._build_few_shot_block(search_result.stage)

        length_rule = _LENGTH_RULES_BY_STAGE.get(search_result.stage, DEFAULT_LENGTH_RULE)
        # NYT_GAMES_LENGTH_RULE already carries the trick-category warning --
        # only layer the standalone note on top when a *different* rule won
        # (reddit/default) but the content is clearly NYT-game-sourced anyway.
        nyt_games_note = (
            NYT_GAMES_ACCURACY_NOTE
            if length_rule is not NYT_GAMES_LENGTH_RULE and mentions_nyt_games(search_result.formatted)
            else ""
        )
        prompt = EXPLANATION_PROMPT.format(
            title=article.normalized_title,
            summary=article.summary or article.extract[:200],
            source_type=search_result.stage,
            results=search_result.formatted[:3000],
            few_shot_block=few_shot_block,
            length_rule=length_rule,
            nyt_games_note=nyt_games_note,
        )
        trending_reason = self.llm_client.generate(
            prompt=prompt,
            model=EXPLANATION_MODEL,
            temperature=EXPLANATION_TEMPERATURE,
            max_tokens=EXPLANATION_MAX_TOKENS,
        )

        short_prompt = SHORT_PROMPT.format(
            title=article.normalized_title,
            summary=article.summary or article.extract[:200],
            trending_reason=trending_reason,
        )
        trending_reason_short = self.llm_client.generate(
            prompt=short_prompt,
            model=SHORT_MODEL,
            temperature=SHORT_TEMPERATURE,
            max_tokens=SHORT_MAX_TOKENS,
        )

        return trending_reason, trending_reason_short

    def _build_few_shot_block(self, source: str) -> str:
        """Pull 2 top examples from the bank and format as a few-shot block."""
        if self.example_bank is None:
            return ""
        try:
            examples = self.example_bank.get_examples(source, limit=2)
        except Exception:
            return ""
        if not examples:
            return ""
        lines = ["\nHere are examples of high-quality explanations:\n"]
        for i, ex in enumerate(examples, 1):
            clipped = _first_n_sentences(ex.get("trending_reason") or "", n=3)
            lines.append(f"Example {i}:")
            lines.append(f"  Search results: {ex['raw_input'][:300]}")
            lines.append(f"  Explanation: {clipped}\n")
        return "\n".join(lines) + "\n"


def _first_n_sentences(text: str, n: int = 3) -> str:
    """Use only the opening sentences of banked examples so few-shot models tight prose."""
    text = text.strip()
    if not text:
        return text
    parts = re.split(r"(?<=[.!?])\s+", text)
    if len(parts) <= n:
        return text
    return " ".join(parts[:n]).strip()
