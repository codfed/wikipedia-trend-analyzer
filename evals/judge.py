"""LLM-as-judge rubrics for the v2 pipeline fields."""
import json
import re
from dataclasses import dataclass

from pipeline.models import Article
from llm.client import LLMClient

JUDGE_MODEL = "claude-haiku-4-5-20251001"
JUDGE_TEMPERATURE = 0.0
JUDGE_MAX_TOKENS = 256


@dataclass
class EvalResult:
    field: str
    score: int          # 1–5
    reasoning: str
    passed: bool        # score >= 3


class LLMJudge:
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    # ------------------------------------------------------------------
    # Public scoring methods
    # ------------------------------------------------------------------

    def score_trending_reason(
        self, article: Article, raw_results: str
    ) -> EvalResult:
        """Score trending_reason for relevance, accuracy, and format."""
        if article.trending_reason_source in ("rolling_list", "carried_forward"):
            return EvalResult(
                field="trending_reason",
                score=5,
                reasoning=f"{article.trending_reason_source} article — LLM judging skipped.",
                passed=True,
            )

        if not raw_results:
            text = article.trending_reason.strip()
            if "unclear" in text.lower():
                return EvalResult(
                    field="trending_reason",
                    score=5,
                    reasoning="Correctly uses fallback when no results available.",
                    passed=True,
                )
            return EvalResult(
                field="trending_reason",
                score=2,
                reasoning="No search results but fallback phrase not used.",
                passed=False,
            )

        prompt = f"""You are a strict evaluator of AI-generated explanations for \
why Wikipedia articles are trending.

Article title: {article.title}
Source type: {article.trending_reason_source}

Search results provided to the AI:
{raw_results[:4000]}

AI-generated explanation (trending_reason):
{article.trending_reason}

Score 1–5 on this rubric:
- Relevance: Does the explanation reflect why the article is trending?
- Groundedness: Are all substantive claims in the explanation traceable to the search results? \
Penalise invented facts, unstated dates or figures, or implications not supported by the text.
- Anti-ramble: Is prose tight (no filler, repetitive restatement, or tangential asides)?
- Format: Reasonable length (roughly one to three short sentences). Does NOT start with \
"Here is the reason why…" or "The article is trending because…"? Avoids "spotlight" and "widespread"?

Critical rules for your reasoning field:
- Only allege a specific fact, name, or detail as "unsupported" or "invented" if it appears \
verbatim or as a clear paraphrase IN THE AI-GENERATED EXPLANATION TEXT ABOVE. Quote that \
fragment in your reasoning when you cite a problem. If a detail exists only in the search \
results and not in the explanation, do not treat it as an explanation flaw.
- Do not invent example violations (no hypothetical phrases the explanation does not contain).

Score guide: 5=excellent, 4=good, 3=acceptable, 2=poor, 1=fails rubric.

Respond with ONLY a single-line JSON object:
{{"score": <1-5>, "reasoning": "<one sentence>", "passed": <true|false>}}"""

        return self._call_judge("trending_reason", prompt)

    def score_trending_reason_short(self, article: Article) -> EvalResult:
        """Score trending_reason_short for faithfulness and conciseness."""
        if article.trending_reason_source in ("rolling_list", "carried_forward"):
            return EvalResult(
                field="trending_reason_short",
                score=5,
                reasoning=f"{article.trending_reason_source} article — LLM judging skipped.",
                passed=True,
            )

        text = article.trending_reason_short.strip()
        word_count = len(text.split())

        prompt = f"""You are a strict evaluator of AI-generated short trending summaries.

Article title: {article.title}

Full trending reason (source of truth):
{article.trending_reason}

Short summary to evaluate (trending_reason_short):
{text}

Score 1–5 on this rubric:
- Faithfulness: Uses ONLY facts from the full trending reason? \
  Penalise invented dates, names, or figures.
- No title mention: Does NOT reference "{article.title}"?
- Conciseness: Clear, useful one-liner ({word_count} words) capturing the core reason?

Score guide: 5=excellent, 4=good, 3=acceptable, 2=poor, 1=fails rubric.

Respond with ONLY a single-line JSON object:
{{"score": <1-5>, "reasoning": "<one sentence>", "passed": <true|false>}}"""

        return self._call_judge("trending_reason_short", prompt)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _call_judge(self, field: str, prompt: str) -> EvalResult:
        response = self.llm_client.generate(
            prompt=prompt,
            model=JUDGE_MODEL,
            temperature=JUDGE_TEMPERATURE,
            max_tokens=JUDGE_MAX_TOKENS,
        )

        data = _parse_judge_json_object(response)
        if data is not None:
            try:
                score = int(data.get("score", 1))
                reasoning = str(data.get("reasoning", "")).strip()
                passed = bool(data.get("passed", score >= 3))
                return EvalResult(field=field, score=score, reasoning=reasoning, passed=passed)
            except (TypeError, ValueError):
                pass

        # Fallback: bare digit
        m = re.search(r"\bscore[:\s]+([1-5])\b", response, re.IGNORECASE)
        score = int(m.group(1)) if m else 2
        return EvalResult(
            field=field,
            score=score,
            reasoning=response[:200].strip(),
            passed=score >= 3,
        )


def _parse_judge_json_object(response: str) -> dict | None:
    """Parse first JSON object from judge output; handles `}` inside quoted reasoning."""
    cleaned = response.strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.startswith("```")]
        cleaned = "\n".join(lines).strip()
    start = cleaned.find("{")
    if start < 0:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(cleaned, start)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
