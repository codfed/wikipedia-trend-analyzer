"""All LLM prompts and versioning constants for wikipedia-trends-v2."""

# Increment this whenever a prompt changes.  Saved articles and eval results
# include this version so quality changes can be tracked over time.
PROMPT_VERSION = "v2.2"

# ---------------------------------------------------------------------------
# Summary (always runs, Haiku)
# ---------------------------------------------------------------------------
SUMMARY_MODEL = "claude-haiku-4-5-20251001"
SUMMARY_TEMPERATURE = 0.3
SUMMARY_MAX_TOKENS = 128
SUMMARY_PROMPT = """Given the Wikipedia extract below, write a short description \
that does NOT mention or reference the article's title.

Rules:
- Focus on describing the subject's content or significance.
- Include enough context to be useful (e.g. country, medium, field).
- Length: 8–15 words (shorter is better).

Title: {title}
Extract: {extract}"""

# ---------------------------------------------------------------------------
# Relevance gate (Haiku, structured JSON output)
# ---------------------------------------------------------------------------
RELEVANCE_MODEL = "claude-haiku-4-5-20251001"
RELEVANCE_TEMPERATURE = 0.0
RELEVANCE_MAX_TOKENS = 64
RELEVANCE_PROMPT = """You are deciding whether search results are relevant to \
explaining why a Wikipedia article is suddenly trending.

Article title: {title}
Article summary: {summary}

Search results:
{results}

Does the search content directly explain or strongly relate to why "{title}" \
is receiving unusual traffic right now?

Respond with ONLY valid JSON on one line:
{{"relevant": <true|false>, "confidence": <0.0-1.0>}}"""

# ---------------------------------------------------------------------------
# Explanation generation (Sonnet, with optional few-shot examples)
# ---------------------------------------------------------------------------
EXPLANATION_MODEL = "claude-sonnet-4-6"
EXPLANATION_TEMPERATURE = 0.3
EXPLANATION_MAX_TOKENS = 512
EXPLANATION_PROMPT = """You are a concise news analysis assistant.

Your task: explain why the Wikipedia article "{title}" is currently trending, \
using ONLY the search results below. Every substantive claim must be directly \
supported by those results—no speculation, no invented names, dates, numbers, \
or causal links that the results do not state.

Rules:
- One clear thread: lead with the main reason, then only what is needed for context. \
Use at most three short sentences; one or two is better if that fully answers it.
- Stay direct: no filler, no meandering asides, no repeating the same point in different words.
- Do NOT hedge with "likely", "perhaps", "may have", or similar unless the search text \
uses that uncertainty explicitly.
- Light tone or whimsy is fine only if it adds no new factual claims and does not wander.
- Do NOT start with "Here is the reason why…" or "The article is trending because…"
- Avoid "spotlight" and "widespread".
{few_shot_block}
Search results ({source_type}):
{results}

Article summary: {summary}

Explanation:"""

# ---------------------------------------------------------------------------
# Short summary (Haiku, condenses the full explanation)
# ---------------------------------------------------------------------------
SHORT_MODEL = "claude-haiku-4-5-20251001"
SHORT_TEMPERATURE = 0.2
SHORT_MAX_TOKENS = 128
SHORT_PROMPT = """Compress the trending reason below into a single concise summary.

Rules:
- Ensure {title} is clearly stated and established.
- Be concise — one tight sentence, as short as the content allows.
- Use only facts explicitly stated in the trending reason.
- Only include dates if they appear verbatim in the text below.

Trending reason:
{trending_reason}

Short summary:"""
